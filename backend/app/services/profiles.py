from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentProfile, Project
from app.domain.enums import AgentType
from app.llm.dependencies import get_provider_registry
from app.llm.providers.http import ProviderConfigurationError
from app.llm.router import AgentModelConfig, LLMRouter
from app.schemas.profiles import AgentProfileCreate, AgentProfileUpdate
from app.services.errors import (
    AgentProfileAlreadyExistsError,
    AgentProfileInvalidError,
    AgentProfileNotFoundError,
)


async def create_profile(
    session: AsyncSession, payload: AgentProfileCreate
) -> AgentProfile:
    _validate_providers(payload)
    if await session.scalar(
        select(AgentProfile.id).where(AgentProfile.name == payload.name).limit(1)
    ):
        raise AgentProfileAlreadyExistsError(payload.name)
    profile = AgentProfile(
        name=payload.name,
        description=payload.description,
        agents=_serialize_agents(payload),
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def list_profiles(session: AsyncSession) -> Sequence[AgentProfile]:
    return (
        await session.scalars(
            select(AgentProfile).order_by(AgentProfile.name.asc())
        )
    ).all()


async def get_profile(session: AsyncSession, profile_id: UUID) -> AgentProfile:
    profile = await session.get(AgentProfile, str(profile_id))
    if profile is None:
        raise AgentProfileNotFoundError(str(profile_id))
    return profile


async def update_profile(
    session: AsyncSession, profile_id: UUID, payload: AgentProfileUpdate
) -> AgentProfile:
    profile = await get_profile(session, profile_id)
    _validate_providers(payload)
    duplicate = await session.scalar(
        select(AgentProfile.id)
        .where(AgentProfile.name == payload.name, AgentProfile.id != profile.id)
        .limit(1)
    )
    if duplicate:
        raise AgentProfileAlreadyExistsError(payload.name)
    profile.name = payload.name
    profile.description = payload.description
    profile.agents = _serialize_agents(payload)
    await session.commit()
    await session.refresh(profile)
    return profile


async def delete_profile(session: AsyncSession, profile_id: UUID) -> None:
    profile = await get_profile(session, profile_id)
    projects = await session.scalars(
        select(Project).where(Project.agent_profile_id == profile.id)
    )
    for project in projects.all():
        project.agent_profile_id = None
    await session.delete(profile)
    await session.commit()


async def router_for_project(
    session: AsyncSession, project_id: UUID, fallback: LLMRouter
) -> LLMRouter:
    profile_id = await session.scalar(
        select(Project.agent_profile_id).where(Project.id == str(project_id)).limit(1)
    )
    if profile_id is None:
        return fallback
    return await router_for_profile(session, profile_id, fallback)


async def router_for_profile(
    session: AsyncSession, profile_id: str | None, fallback: LLMRouter
) -> LLMRouter:
    if profile_id is None:
        return fallback
    profile = await session.get(AgentProfile, profile_id)
    if profile is None:
        return fallback
    registry = get_provider_registry()
    fallbacks = {
        AgentType.IMPROVER: AgentType.BUILDER,
        AgentType.PRODUCT_ARCHITECT: AgentType.BUILDER,
        AgentType.SOLUTION_ARCHITECT: AgentType.BUILDER,
        AgentType.TECHNICAL_CRITIC: AgentType.CRITIC,
        AgentType.ROADMAP_PLANNER: AgentType.JUDGE,
    }
    return LLMRouter(
        {
            agent: registry.create(
                AgentModelConfig(
                    provider=str(
                        _profile_agent_config(profile.agents, agent, fallbacks)["provider"]
                    ),
                    model=str(
                        _profile_agent_config(profile.agents, agent, fallbacks)["model"]
                    ),
                    input_cost_per_million=Decimal(
                        str(
                            _profile_agent_config(profile.agents, agent, fallbacks).get(
                                "input_cost_per_million", "0"
                            )
                        )
                    ),
                    cached_input_cost_per_million=_optional_decimal(
                        _profile_agent_config(profile.agents, agent, fallbacks).get(
                            "cached_input_cost_per_million"
                        )
                    ),
                    output_cost_per_million=Decimal(
                        str(
                            _profile_agent_config(profile.agents, agent, fallbacks).get(
                                "output_cost_per_million", "0"
                            )
                        )
                    ),
                )
            )
            for agent in AgentType
        }
    )


def _profile_agent_config(
    agents: dict[str, object],
    agent: AgentType,
    fallbacks: dict[AgentType, AgentType],
) -> dict[str, object]:
    config = agents.get(agent.value)
    if not isinstance(config, dict):
        fallback = fallbacks.get(agent)
        config = agents.get(fallback.value) if fallback is not None else None
    if not isinstance(config, dict):
        raise AgentProfileInvalidError(f"Profile has no configuration for {agent.value}")
    return config


def _serialize_agents(payload: AgentProfileCreate) -> dict[str, object]:
    serialized = {
        agent.value: config.model_dump(mode="json")
        for agent, config in payload.agents.items()
    }
    fallbacks = {
        AgentType.IMPROVER: AgentType.BUILDER,
        AgentType.PRODUCT_ARCHITECT: AgentType.BUILDER,
        AgentType.SOLUTION_ARCHITECT: AgentType.BUILDER,
        AgentType.TECHNICAL_CRITIC: AgentType.CRITIC,
        AgentType.ROADMAP_PLANNER: AgentType.JUDGE,
    }
    for agent, fallback in fallbacks.items():
        serialized.setdefault(agent.value, dict(serialized[fallback.value]))
    return serialized


def _validate_providers(payload: AgentProfileCreate) -> None:
    registry = get_provider_registry()
    unknown = sorted(
        {
            config.provider
            for config in payload.agents.values()
            if not registry.supports(config.provider)
        }
    )
    if unknown:
        raise AgentProfileInvalidError(
            f"Unknown provider adapters: {', '.join(unknown)}"
        )
    for agent, config in payload.agents.items():
        try:
            registry.create(
                AgentModelConfig(
                    provider=config.provider,
                    model=config.model,
                    input_cost_per_million=config.input_cost_per_million,
                    cached_input_cost_per_million=config.cached_input_cost_per_million,
                    output_cost_per_million=config.output_cost_per_million,
                )
            )
        except (ProviderConfigurationError, ValueError) as exc:
            raise AgentProfileInvalidError(f"{agent.value}: {exc}") from exc


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None or str(value).strip() == "" else Decimal(str(value))
