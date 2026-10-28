from typing import Any
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import LLMAttempt
from app.database.models import AgentRun, Project
from app.domain.enums import AgentType
from app.llm.base import LLMProvider


async def add_agent_runs(
    session: AsyncSession,
    *,
    project_id: str,
    agent: AgentType,
    provider: LLMProvider,
    prompt_version: str,
    input_data: dict[str, Any],
    attempts: tuple[LLMAttempt, ...],
    round_id: str | None = None,
) -> list[AgentRun]:
    runs: list[AgentRun] = []
    incurred_cost = Decimal("0")
    for attempt in attempts:
        response = attempt.response
        if response is not None:
            incurred_cost += response.estimated_cost
        run = AgentRun(
            project_id=project_id,
            round_id=round_id,
            agent=agent,
            provider=provider.provider_name,
            model=response.model if response is not None else provider.model_name,
            prompt_version=prompt_version,
            input_json=input_data,
            output_json=attempt.output_json,
            input_tokens=response.input_tokens if response is not None else 0,
            output_tokens=response.output_tokens if response is not None else 0,
            cached_input_tokens=(
                response.cached_input_tokens if response is not None else 0
            ),
            reasoning_tokens=(response.reasoning_tokens if response is not None else 0),
            web_search_calls=(
                response.web_search_calls if response is not None else 0
            ),
            tool_cost=response.tool_cost if response is not None else 0,
            web_sources=(
                [item.model_dump(mode="json") for item in response.web_sources]
                if response is not None
                else []
            ),
            estimated_cost=(response.estimated_cost if response is not None else 0),
            execution_time=attempt.execution_time,
            error=attempt.error,
        )
        session.add(run)
        runs.append(run)
    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} disappeared while recording runs")
    project.total_cost = Decimal(project.total_cost) + incurred_cost
    return runs
