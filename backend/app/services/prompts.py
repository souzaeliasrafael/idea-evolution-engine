from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentPromptVersion
from app.domain.enums import AgentType
from app.llm.prompts import load_default_prompt
from app.schemas.prompts import AgentPromptRead, AgentPromptUpdate


@dataclass(frozen=True)
class EffectivePrompt:
    content: str
    version: str


async def get_effective_prompt(
    session: AsyncSession, agent: AgentType
) -> EffectivePrompt:
    active = await _active_version(session, agent)
    if active is not None:
        return EffectivePrompt(
            content=active.content,
            version=f"custom-v{active.version}",
        )
    content, version = load_default_prompt(agent)
    return EffectivePrompt(content=content, version=version)


async def list_prompt_configurations(
    session: AsyncSession,
) -> list[AgentPromptRead]:
    return [await get_prompt_configuration(session, agent) for agent in AgentType]


async def get_prompt_configuration(
    session: AsyncSession, agent: AgentType
) -> AgentPromptRead:
    default_content, default_version = load_default_prompt(agent)
    active = await _active_version(session, agent)
    return AgentPromptRead(
        agent=agent,
        content=active.content if active is not None else default_content,
        version=f"custom-v{active.version}" if active is not None else default_version,
        customized=active is not None,
        default_content=default_content,
        default_version=default_version,
        updated_at=active.created_at if active is not None else None,
    )


async def create_prompt_version(
    session: AsyncSession,
    agent: AgentType,
    payload: AgentPromptUpdate,
) -> AgentPromptRead:
    latest_version = await session.scalar(
        select(func.max(AgentPromptVersion.version)).where(
            AgentPromptVersion.agent == agent
        )
    )
    await session.execute(
        update(AgentPromptVersion)
        .where(
            AgentPromptVersion.agent == agent,
            AgentPromptVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    session.add(
        AgentPromptVersion(
            agent=agent,
            version=int(latest_version or 0) + 1,
            content=payload.content,
            is_active=True,
        )
    )
    await session.commit()
    return await get_prompt_configuration(session, agent)


async def reset_prompt(
    session: AsyncSession, agent: AgentType
) -> AgentPromptRead:
    await session.execute(
        update(AgentPromptVersion)
        .where(
            AgentPromptVersion.agent == agent,
            AgentPromptVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    await session.commit()
    return await get_prompt_configuration(session, agent)


async def list_prompt_versions(
    session: AsyncSession, agent: AgentType
) -> Sequence[AgentPromptVersion]:
    return (
        await session.scalars(
            select(AgentPromptVersion)
            .where(AgentPromptVersion.agent == agent)
            .order_by(
                AgentPromptVersion.version.desc(), AgentPromptVersion.id.desc()
            )
        )
    ).all()


async def _active_version(
    session: AsyncSession, agent: AgentType
) -> AgentPromptVersion | None:
    return await session.scalar(
        select(AgentPromptVersion)
        .where(
            AgentPromptVersion.agent == agent,
            AgentPromptVersion.is_active.is_(True),
        )
        .order_by(
            AgentPromptVersion.version.desc(), AgentPromptVersion.id.desc()
        )
        .limit(1)
    )
