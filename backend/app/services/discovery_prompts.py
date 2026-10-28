from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DiscoveryPromptVersion
from app.domain.enums import DiscoveryAgentType
from app.llm.prompts import load_prompt
from app.schemas.discovery import DiscoveryPromptRead, DiscoveryPromptUpdate


@dataclass(frozen=True)
class EffectiveDiscoveryPrompt:
    content: str
    version: str


async def get_effective_prompt(session: AsyncSession, agent: DiscoveryAgentType) -> EffectiveDiscoveryPrompt:
    active = await _active_version(session, agent)
    if active is not None:
        return EffectiveDiscoveryPrompt(active.content, f"custom-v{active.version}")
    content, version = _default_prompt(agent)
    return EffectiveDiscoveryPrompt(content, version)


async def list_configurations(session: AsyncSession) -> list[DiscoveryPromptRead]:
    return [await get_configuration(session, agent) for agent in DiscoveryAgentType]


async def get_configuration(session: AsyncSession, agent: DiscoveryAgentType) -> DiscoveryPromptRead:
    default_content, default_version = _default_prompt(agent)
    active = await _active_version(session, agent)
    return DiscoveryPromptRead(
        agent=agent,
        content=active.content if active else default_content,
        version=f"custom-v{active.version}" if active else default_version,
        customized=active is not None,
        default_content=default_content,
        default_version=default_version,
        updated_at=active.created_at if active else None,
    )


async def create_version(
    session: AsyncSession, agent: DiscoveryAgentType, payload: DiscoveryPromptUpdate
) -> DiscoveryPromptRead:
    latest = await session.scalar(select(func.max(DiscoveryPromptVersion.version)).where(DiscoveryPromptVersion.agent == agent))
    await session.execute(update(DiscoveryPromptVersion).where(
        DiscoveryPromptVersion.agent == agent, DiscoveryPromptVersion.is_active.is_(True)
    ).values(is_active=False))
    session.add(DiscoveryPromptVersion(agent=agent, version=int(latest or 0) + 1, content=payload.content, is_active=True))
    await session.commit()
    return await get_configuration(session, agent)


async def reset(session: AsyncSession, agent: DiscoveryAgentType) -> DiscoveryPromptRead:
    await session.execute(update(DiscoveryPromptVersion).where(
        DiscoveryPromptVersion.agent == agent, DiscoveryPromptVersion.is_active.is_(True)
    ).values(is_active=False))
    await session.commit()
    return await get_configuration(session, agent)


async def list_versions(session: AsyncSession, agent: DiscoveryAgentType) -> Sequence[DiscoveryPromptVersion]:
    return (await session.scalars(select(DiscoveryPromptVersion).where(
        DiscoveryPromptVersion.agent == agent
    ).order_by(DiscoveryPromptVersion.version.desc(), DiscoveryPromptVersion.id.desc()))).all()


async def _active_version(session: AsyncSession, agent: DiscoveryAgentType) -> DiscoveryPromptVersion | None:
    return await session.scalar(select(DiscoveryPromptVersion).where(
        DiscoveryPromptVersion.agent == agent, DiscoveryPromptVersion.is_active.is_(True)
    ).order_by(DiscoveryPromptVersion.version.desc(), DiscoveryPromptVersion.id.desc()).limit(1))


def _default_prompt(agent: DiscoveryAgentType) -> tuple[str, str]:
    version = "v1"
    return load_prompt(agent.value.lower(), version), version
