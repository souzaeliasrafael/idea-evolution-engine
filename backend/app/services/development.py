from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentExecutionError, AgentResult
from app.agents.development import (
    ProductArchitectAgent,
    RoadmapPlannerAgent,
    SolutionArchitectAgent,
    TechnicalCriticAgent,
)
from app.core.config import get_settings
from app.database.models import (
    AgentRun,
    Criticism,
    DecisionRecord,
    DevelopmentBlueprint,
    Project,
    utc_now,
)
from app.domain.enums import AgentType, DevelopmentBlueprintStatus
from app.llm.base import LLMProvider
from app.llm.router import LLMRouter
from app.schemas.development import DevelopmentBlueprintCreate
from app.services.agent_runs import add_agent_runs
from app.services.budget import require_budget_available
from app.services.context_compaction import compact_concept, compact_records
from app.services.errors import (
    AgentExecutionFailedError,
    BudgetLimitReachedError,
    DevelopmentBlueprintAlreadyRunningError,
    ProjectNotFoundError,
    ProjectNotStructuredError,
)
from app.services.knowledge import list_evidence, list_hypotheses
from app.services.project_context import get_project_and_latest_version
from app.services.prompts import get_effective_prompt


async def generate_blueprint(
    session: AsyncSession,
    project_id: UUID,
    router: LLMRouter,
    payload: DevelopmentBlueprintCreate,
) -> DevelopmentBlueprint:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    require_budget_available(project)
    running = await session.scalar(
        select(DevelopmentBlueprint.id)
        .where(
            DevelopmentBlueprint.project_id == project.id,
            DevelopmentBlueprint.status == DevelopmentBlueprintStatus.RUNNING,
        )
        .limit(1)
    )
    if running is not None:
        raise DevelopmentBlueprintAlreadyRunningError(project.id)
    try:
        _, current_version = await get_project_and_latest_version(session, project_id)
    except ProjectNotStructuredError:
        raise

    current_number = await session.scalar(
        select(func.max(DevelopmentBlueprint.version)).where(
            DevelopmentBlueprint.project_id == project.id
        )
    )
    blueprint = DevelopmentBlueprint(
        project_id=project.id,
        version=int(current_number or 0) + 1,
        status=DevelopmentBlueprintStatus.RUNNING,
        architecture_alternatives=payload.architecture_alternatives,
        user_context=payload.user_context,
        max_ai_budget=payload.max_ai_budget,
        architecture_options=[],
        agent_run_ids=[],
    )
    session.add(blueprint)
    await session.commit()
    await session.refresh(blueprint)
    start_cost = Decimal(project.total_cost)

    try:
        project_context = await _compile_project_context(
            session, project_id, current_version.concept
        )
        product_result = await _run_product_architect(
            session,
            project,
            blueprint,
            router.provider_for(AgentType.PRODUCT_ARCHITECT),
            project_context,
            payload.user_context,
            start_cost,
        )
        blueprint.product_definition = product_result.output.model_dump(mode="json")
        await session.commit()

        options: list[dict[str, Any]] = []
        for option_number in range(1, payload.architecture_alternatives + 1):
            option_result = await _run_solution_architect(
                session,
                project,
                blueprint,
                router.provider_for(AgentType.SOLUTION_ARCHITECT),
                project_context,
                blueprint.product_definition,
                option_number,
                options,
                payload.user_context,
                start_cost,
            )
            options.append(option_result.output.model_dump(mode="json"))
            blueprint.architecture_options = list(options)
            await session.commit()

        review_result = await _run_technical_critic(
            session,
            project,
            blueprint,
            router.provider_for(AgentType.TECHNICAL_CRITIC),
            project_context,
            blueprint.product_definition,
            options,
            payload.user_context,
            start_cost,
        )
        blueprint.technical_review = review_result.output.model_dump(mode="json")
        await session.commit()

        roadmap_result = await _run_roadmap_planner(
            session,
            project,
            blueprint,
            router.provider_for(AgentType.ROADMAP_PLANNER),
            project_context,
            blueprint.product_definition,
            options,
            blueprint.technical_review,
            payload.user_context,
            start_cost,
        )
        blueprint.final_blueprint = roadmap_result.output.model_dump(mode="json")
        blueprint.status = DevelopmentBlueprintStatus.COMPLETED
        blueprint.completed_at = utc_now()
        await _update_blueprint_cost(session, project, blueprint, start_cost)
        await session.commit()
        await session.refresh(blueprint)
        return blueprint
    except Exception as exc:
        await session.rollback()
        failed = await session.get(DevelopmentBlueprint, blueprint.id)
        current_project = await session.get(Project, project.id)
        if failed is not None:
            failed.status = DevelopmentBlueprintStatus.FAILED
            failed.error = f"{type(exc).__name__}: {exc}"[:2000]
            failed.completed_at = utc_now()
            if current_project is not None:
                failed.estimated_cost = max(
                    Decimal("0"), Decimal(current_project.total_cost) - start_cost
                )
            await session.commit()
        raise


async def list_blueprints(
    session: AsyncSession, project_id: UUID
) -> Sequence[DevelopmentBlueprint]:
    if await session.get(Project, str(project_id)) is None:
        raise ProjectNotFoundError(str(project_id))
    return (
        await session.scalars(
            select(DevelopmentBlueprint)
            .where(DevelopmentBlueprint.project_id == str(project_id))
            .order_by(DevelopmentBlueprint.version.desc())
        )
    ).all()


async def _run_product_architect(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    provider: LLMProvider,
    project_context: dict[str, Any],
    user_context: str | None,
    start_cost: Decimal,
) -> AgentResult[Any]:
    agent = await _product_agent(session, provider)
    return await _execute_stage(
        session,
        project,
        blueprint,
        AgentType.PRODUCT_ARCHITECT,
        provider,
        agent,
        lambda: agent.run(project_context=project_context, user_context=user_context),
        start_cost,
    )


async def _run_solution_architect(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    provider: LLMProvider,
    project_context: dict[str, Any],
    product_definition: dict[str, Any],
    option_number: int,
    options: list[dict[str, Any]],
    user_context: str | None,
    start_cost: Decimal,
) -> AgentResult[Any]:
    agent = await _solution_agent(session, provider)
    return await _execute_stage(
        session,
        project,
        blueprint,
        AgentType.SOLUTION_ARCHITECT,
        provider,
        agent,
        lambda: agent.run(
            project_context=project_context,
            product_definition=product_definition,
            option_number=option_number,
            previous_options=options,
            user_context=user_context,
        ),
        start_cost,
    )


async def _run_technical_critic(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    provider: LLMProvider,
    project_context: dict[str, Any],
    product_definition: dict[str, Any],
    options: list[dict[str, Any]],
    user_context: str | None,
    start_cost: Decimal,
) -> AgentResult[Any]:
    agent = await _critic_agent(session, provider)
    return await _execute_stage(
        session,
        project,
        blueprint,
        AgentType.TECHNICAL_CRITIC,
        provider,
        agent,
        lambda: agent.run(
            project_context=project_context,
            product_definition=product_definition,
            architecture_options=options,
            user_context=user_context,
        ),
        start_cost,
    )


async def _run_roadmap_planner(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    provider: LLMProvider,
    project_context: dict[str, Any],
    product_definition: dict[str, Any],
    options: list[dict[str, Any]],
    review: dict[str, Any],
    user_context: str | None,
    start_cost: Decimal,
) -> AgentResult[Any]:
    agent = await _roadmap_agent(session, provider)
    return await _execute_stage(
        session,
        project,
        blueprint,
        AgentType.ROADMAP_PLANNER,
        provider,
        agent,
        lambda: agent.run(
            project_context=project_context,
            product_definition=product_definition,
            architecture_options=options,
            technical_review=review,
            user_context=user_context,
        ),
        start_cost,
    )


async def _execute_stage(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    agent_type: AgentType,
    provider: LLMProvider,
    agent: Any,
    execution: Callable[[], Awaitable[AgentResult[Any]]],
    start_cost: Decimal,
) -> AgentResult[Any]:
    await session.refresh(project)
    require_budget_available(project)
    if (
        blueprint.max_ai_budget is not None
        and Decimal(project.total_cost) - start_cost >= blueprint.max_ai_budget
    ):
        raise BudgetLimitReachedError(
            f"Development blueprint budget reached for {project.id}"
        )
    try:
        result = await execution()
    except AgentExecutionError as exc:
        runs = await add_agent_runs(
            session,
            project_id=project.id,
            agent=agent_type,
            provider=provider,
            prompt_version=agent.prompt_version,
            input_data=exc.input_data,
            attempts=exc.attempts,
        )
        await session.flush()
        blueprint.agent_run_ids = [
            *blueprint.agent_run_ids,
            *(run.id for run in runs),
        ]
        await _update_blueprint_cost(session, project, blueprint, start_cost)
        await session.commit()
        raise AgentExecutionFailedError(
            project.id,
            agent=agent_type.value,
            attempts=len(exc.attempts),
            last_error=exc.attempts[-1].error if exc.attempts else None,
        ) from exc

    runs = await add_agent_runs(
        session,
        project_id=project.id,
        agent=agent_type,
        provider=provider,
        prompt_version=result.prompt_version,
        input_data=result.input_data,
        attempts=result.attempts,
    )
    await session.flush()
    blueprint.agent_run_ids = [
        *blueprint.agent_run_ids,
        *(run.id for run in runs),
    ]
    await _update_blueprint_cost(session, project, blueprint, start_cost)
    await session.commit()
    return result


async def _update_blueprint_cost(
    session: AsyncSession,
    project: Project,
    blueprint: DevelopmentBlueprint,
    start_cost: Decimal,
) -> None:
    await session.flush()
    blueprint.estimated_cost = max(
        Decimal("0"), Decimal(project.total_cost) - start_cost
    )


async def _compile_project_context(
    session: AsyncSession,
    project_id: UUID,
    current_concept: dict[str, Any],
) -> dict[str, Any]:
    hypotheses = await list_hypotheses(session, project_id)
    evidence = await list_evidence(session, project_id)
    criticisms = list(
        (
            await session.scalars(
                select(Criticism)
                .where(Criticism.project_id == str(project_id))
                .order_by(Criticism.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    decisions = list(
        (
            await session.scalars(
                select(DecisionRecord)
                .where(DecisionRecord.project_id == str(project_id))
                .order_by(DecisionRecord.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    research_outputs = list(
        (
            await session.scalars(
                select(AgentRun.output_json)
                .where(
                    AgentRun.project_id == str(project_id),
                    AgentRun.agent == AgentType.RESEARCHER,
                    AgentRun.error.is_(None),
                    AgentRun.output_json.is_not(None),
                )
                .order_by(AgentRun.created_at.desc())
                .limit(12)
            )
        ).all()
    )
    evidence_dump = [item.model_dump(mode="json") for item in evidence]
    return {
        "current_concept": compact_concept(current_concept),
        "hypotheses": compact_records(
            [item.model_dump(mode="json") for item in hypotheses], limit=100
        ),
        "evidence": compact_records(evidence_dump, limit=100),
        "criticisms": compact_records(
            [
                {
                    "title": item.title,
                    "severity": item.severity.value,
                    "claim": item.claim,
                    "reason": item.reason,
                    "evidence_needed": item.evidence_needed,
                }
                for item in criticisms
            ],
            limit=50,
        ),
        "decisions": compact_records(
            [
                {
                    "decision": item.decision.value,
                    "reason": item.reason,
                    "critical_blockers": item.critical_blockers,
                    "unknowns": item.most_important_unknowns,
                    "next_actions": item.next_actions,
                }
                for item in decisions
            ],
            limit=20,
        ),
        "research_outputs": compact_records(
            [item for item in research_outputs if isinstance(item, dict)], limit=12
        ),
        "allowed_evidence_ids": [item["id"] for item in evidence_dump[:12]],
    }


async def _product_agent(
    session: AsyncSession, provider: LLMProvider
) -> ProductArchitectAgent:
    settings = get_settings()
    prompt = await get_effective_prompt(session, AgentType.PRODUCT_ARCHITECT)
    return ProductArchitectAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=prompt.content,
        prompt_version=prompt.version,
    )


async def _solution_agent(
    session: AsyncSession, provider: LLMProvider
) -> SolutionArchitectAgent:
    settings = get_settings()
    prompt = await get_effective_prompt(session, AgentType.SOLUTION_ARCHITECT)
    return SolutionArchitectAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=prompt.content,
        prompt_version=prompt.version,
    )


async def _critic_agent(
    session: AsyncSession, provider: LLMProvider
) -> TechnicalCriticAgent:
    settings = get_settings()
    prompt = await get_effective_prompt(session, AgentType.TECHNICAL_CRITIC)
    return TechnicalCriticAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=prompt.content,
        prompt_version=prompt.version,
    )


async def _roadmap_agent(
    session: AsyncSession, provider: LLMProvider
) -> RoadmapPlannerAgent:
    settings = get_settings()
    prompt = await get_effective_prompt(session, AgentType.ROADMAP_PLANNER)
    return RoadmapPlannerAgent(
        provider,
        max_attempts=settings.llm_max_attempts,
        retry_max_output_tokens=settings.llm_retry_max_output_tokens,
        prompt=prompt.content,
        prompt_version=prompt.version,
    )
