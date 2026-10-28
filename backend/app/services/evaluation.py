from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError
from app.agents.builder import BuilderAgent
from app.agents.critic import CriticAgent
from app.core.config import get_settings
from app.database.models import Criticism, IdeaVersion, Project
from app.domain.enums import AgentType, HypothesisOrigin
from app.llm.base import LLMProvider
from app.schemas.evaluation import BuilderOutput, CriticOutput
from app.schemas.idea import IdeaConcept
from app.services.agent_runs import add_agent_runs
from app.services.budget import require_budget_available
from app.services.context_compaction import (
    compact_accumulated_context,
    compact_concept,
    compact_records,
)
from app.services.errors import (
    AgentExecutionFailedError,
    ProjectNotFoundError,
)
from app.services.project_context import get_project_and_latest_version
from app.services.knowledge import (
    list_evidence,
    list_hypotheses,
    register_concept_hypotheses,
)
from app.services.prompts import get_effective_prompt


async def run_builder(
    session: AsyncSession,
    project_id: UUID,
    provider: LLMProvider,
    *,
    round_id: str | None = None,
    workflow_instruction: dict[str, Any] | None = None,
    user_context: str | None = None,
    accumulated_context: dict[str, Any] | None = None,
    workflow_stage: str = "INDEPENDENT",
) -> BuilderOutput:
    project, current_version = await get_project_and_latest_version(session, project_id)
    require_budget_available(project)
    criticism_rows = list(
        (
            await session.scalars(
                select(Criticism)
                .where(Criticism.project_id == project.id)
                .order_by(Criticism.created_at.asc(), Criticism.id.asc())
            )
        ).all()
    )
    previous_criticisms = compact_records(
        [_criticism_input(row) for row in criticism_rows], limit=50
    )
    hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    effective_prompt = await get_effective_prompt(session, AgentType.BUILDER)
    settings = get_settings()
    agent = BuilderAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        initial_max_output_tokens=settings.builder_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
    )

    try:
        result = await agent.run(
            current_concept=compact_concept(current_version.concept),
            previous_criticisms=previous_criticisms,
            hypotheses=compact_records(
                [item.model_dump(mode="json") for item in hypotheses], limit=100
            ),
            evidence=compact_records(
                [item.model_dump(mode="json") for item in evidence], limit=80
            ),
            accumulated_context=compact_accumulated_context(accumulated_context),
            workflow_stage=workflow_stage,
            workflow_instruction=workflow_instruction,
            user_context=user_context,
        )
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=project.id,
            agent=AgentType.BUILDER,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
            round_id=round_id,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=AgentType.BUILDER.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    await add_agent_runs(
        session,
        project_id=project.id,
        agent=AgentType.BUILDER,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
        round_id=round_id,
    )
    changes = result.output.proposed_changes or result.output.improvements
    if not changes:
        changes = ["Builder produced a new evaluated concept"]
    persisted_concept = IdeaConcept.model_validate(
        {
            **result.output.new_concept.model_dump(mode="json"),
            "raw_idea": current_version.concept["raw_idea"],
        }
    ).model_dump(mode="json")
    new_version = IdeaVersion(
        project_id=project.id,
        version=current_version.version + 1,
        parent_version_id=current_version.id,
        reason_for_change="Builder refinement",
        created_by=AgentType.BUILDER,
        changes=changes,
        concept=persisted_concept,
    )
    session.add(new_version)
    await session.flush()
    await register_concept_hypotheses(
        session,
        project_id=project.id,
        source_version_id=new_version.id,
        concept=persisted_concept,
        origin=HypothesisOrigin.BUILDER,
        additional_hypotheses=result.output.new_hypotheses,
    )
    await session.commit()
    return result.output


async def run_critic(
    session: AsyncSession,
    project_id: UUID,
    provider: LLMProvider,
    *,
    round_id: str | None = None,
    user_context: str | None = None,
    accumulated_context: dict[str, Any] | None = None,
) -> CriticOutput:
    project, current_version = await get_project_and_latest_version(session, project_id)
    require_budget_available(project)
    hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    effective_prompt = await get_effective_prompt(session, AgentType.CRITIC)
    settings = get_settings()
    agent = CriticAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=effective_prompt.content,
        prompt_version=effective_prompt.version,
    )

    try:
        result = await agent.run(
            current_concept=compact_concept(current_version.concept),
            hypotheses=compact_records(
                [item.model_dump(mode="json") for item in hypotheses], limit=100
            ),
            evidence=compact_records(
                [item.model_dump(mode="json") for item in evidence], limit=80
            ),
            accumulated_context=compact_accumulated_context(accumulated_context),
            user_context=user_context,
        )
    except AgentExecutionError as exc:
        await add_agent_runs(
            session,
            project_id=project.id,
            agent=AgentType.CRITIC,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
            round_id=round_id,
        )
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=AgentType.CRITIC.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    runs = await add_agent_runs(
        session,
        project_id=project.id,
        agent=AgentType.CRITIC,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
        round_id=round_id,
    )
    await session.flush()
    successful_run = runs[-1]
    for criticism in result.output.criticisms:
        session.add(
            Criticism(
                project_id=project.id,
                idea_version_id=current_version.id,
                agent_run_id=successful_run.id,
                **criticism.model_dump(mode="python"),
            )
        )
    await session.commit()
    return result.output


def _criticism_input(criticism: Criticism) -> dict[str, Any]:
    return {
        "title": criticism.title,
        "severity": criticism.severity.value,
        "claim": criticism.claim,
        "reason": criticism.reason,
        "affected_hypotheses": criticism.affected_hypotheses,
        "evidence_needed": criticism.evidence_needed,
        "condition_that_refutes_criticism": criticism.condition_that_refutes_criticism,
    }


async def list_criticisms(
    session: AsyncSession, project_id: UUID
) -> list[Criticism]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    rows = await session.scalars(
        select(Criticism)
        .where(Criticism.project_id == str(project_id))
        .order_by(Criticism.created_at.desc(), Criticism.id.desc())
    )
    return list(rows.all())
