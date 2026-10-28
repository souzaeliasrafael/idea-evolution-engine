from collections import defaultdict
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Evidence, Hypothesis, IdeaVersion, Project
from app.domain.enums import (
    EpistemicClassification,
    EvidenceDirection,
    EvidenceOrigin,
    HypothesisOrigin,
    HypothesisStatus,
)
from app.llm.base import WebSource
from app.schemas.knowledge import (
    EvidenceCreate,
    EvidenceRead,
    HypothesisCreate,
    HypothesisRead,
    HypothesisUpdate,
)
from app.services.errors import (
    HypothesisAlreadyExistsError,
    HypothesisNotFoundError,
    ProjectNotFoundError,
)


async def create_hypothesis(
    session: AsyncSession, project_id: UUID, payload: HypothesisCreate
) -> HypothesisRead:
    project = await _require_project(session, project_id)
    existing = await session.scalar(
        select(Hypothesis.id).where(
            Hypothesis.project_id == project.id,
            func.lower(Hypothesis.statement) == payload.statement.lower(),
        )
    )
    if existing is not None:
        raise HypothesisAlreadyExistsError(payload.statement)
    source_version_id = await session.scalar(
        select(IdeaVersion.id)
        .where(IdeaVersion.project_id == project.id)
        .order_by(IdeaVersion.version.desc())
        .limit(1)
    )
    hypothesis = Hypothesis(
        project_id=project.id,
        sequence=await _next_hypothesis_sequence(session, project.id),
        origin=HypothesisOrigin.USER,
        source_version_id=source_version_id,
        **payload.model_dump(mode="python"),
    )
    session.add(hypothesis)
    await session.commit()
    await session.refresh(hypothesis)
    return _hypothesis_read(hypothesis, [])


async def list_hypotheses(
    session: AsyncSession, project_id: UUID
) -> list[HypothesisRead]:
    project = await _require_project(session, project_id)
    hypotheses = list(
        (
            await session.scalars(
                select(Hypothesis)
                .where(Hypothesis.project_id == project.id)
                .order_by(
                    (Hypothesis.impact * (1 - Hypothesis.confidence)).desc(),
                    Hypothesis.sequence.asc(),
                )
            )
        ).all()
    )
    evidence_rows = list(
        (
            await session.scalars(
                select(Evidence)
                .where(Evidence.project_id == project.id)
                .order_by(Evidence.sequence.asc())
            )
        ).all()
    )
    evidence_by_hypothesis: dict[str, list[str]] = defaultdict(list)
    for item in evidence_rows:
        evidence_by_hypothesis[item.hypothesis_id].append(item.code)
    return [
        _hypothesis_read(item, evidence_by_hypothesis[item.id])
        for item in hypotheses
    ]


async def update_hypothesis(
    session: AsyncSession,
    project_id: UUID,
    code: str,
    payload: HypothesisUpdate,
) -> HypothesisRead:
    project = await _require_project(session, project_id)
    hypothesis = await _hypothesis_by_code(session, project.id, code)
    if hypothesis is None:
        raise HypothesisNotFoundError(code)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(hypothesis, field, value)
    await session.commit()
    await session.refresh(hypothesis)
    evidence_codes = list(
        (
            await session.scalars(
                select(Evidence.sequence)
                .where(Evidence.hypothesis_id == hypothesis.id)
                .order_by(Evidence.sequence.asc())
            )
        ).all()
    )
    return _hypothesis_read(
        hypothesis, [f"E{sequence:03d}" for sequence in evidence_codes]
    )


async def create_evidence(
    session: AsyncSession, project_id: UUID, payload: EvidenceCreate
) -> EvidenceRead:
    project = await _require_project(session, project_id)
    hypothesis = await _hypothesis_by_code(session, project.id, payload.hypothesis_id)
    if hypothesis is None:
        raise HypothesisNotFoundError(payload.hypothesis_id)
    evidence = Evidence(
        project_id=project.id,
        sequence=await _next_evidence_sequence(session, project.id),
        hypothesis_id=hypothesis.id,
        agent_run_id=None,
        origin=EvidenceOrigin.USER,
        source=payload.source,
        source_type=payload.source_type,
        claim=payload.claim,
        direction=payload.direction,
        strength=payload.strength,
        epistemic_classification=payload.epistemic_classification,
        url=payload.url,
        date=payload.date,
    )
    session.add(evidence)
    await session.commit()
    await session.refresh(evidence)
    return _evidence_read(evidence, hypothesis.code)


async def list_evidence(
    session: AsyncSession, project_id: UUID
) -> list[EvidenceRead]:
    project = await _require_project(session, project_id)
    rows = (
        await session.execute(
            select(Evidence, Hypothesis)
            .join(Hypothesis, Evidence.hypothesis_id == Hypothesis.id)
            .where(Evidence.project_id == project.id)
            .order_by(Evidence.sequence.asc())
        )
    ).all()
    return [_evidence_read(evidence, hypothesis.code) for evidence, hypothesis in rows]


async def register_concept_hypotheses(
    session: AsyncSession,
    *,
    project_id: str,
    source_version_id: str,
    concept: dict[str, Any],
    origin: HypothesisOrigin,
    additional_hypotheses: Sequence[str] = (),
) -> None:
    candidates: list[tuple[object, str, EpistemicClassification]] = []
    candidates.extend(
        (statement, "TECHNICAL", EpistemicClassification.ASSUMPTION)
        for statement in concept.get("technical_assumptions", [])
    )
    candidates.extend(
        (statement, "BUSINESS", EpistemicClassification.ASSUMPTION)
        for statement in concept.get("business_assumptions", [])
    )
    candidates.extend(
        (statement, "UNKNOWN", EpistemicClassification.UNKNOWN)
        for statement in concept.get("unknowns", [])
    )
    candidates.extend(
        (statement, "GENERAL", EpistemicClassification.ASSUMPTION)
        for statement in additional_hypotheses
    )
    existing_statements = {
        statement.casefold()
        for statement in (
            await session.scalars(
                select(Hypothesis.statement).where(
                    Hypothesis.project_id == project_id
                )
            )
        ).all()
    }
    next_sequence = await _next_hypothesis_sequence(session, project_id)
    for raw_statement, category, classification in candidates:
        statement = str(raw_statement).strip()
        normalized = statement.casefold()
        if not statement or normalized in existing_statements:
            continue
        session.add(
            Hypothesis(
                project_id=project_id,
                sequence=next_sequence,
                statement=statement,
                category=category,
                impact=5,
                confidence=0.0,
                status=HypothesisStatus.OPEN,
                epistemic_classification=classification,
                origin=origin,
                source_version_id=source_version_id,
            )
        )
        existing_statements.add(normalized)
        next_sequence += 1


async def register_web_sources(
    session: AsyncSession,
    *,
    project_id: str,
    hypothesis_code: str,
    agent_run_id: str,
    question: str,
    finding: str,
    sources: Sequence[WebSource],
) -> list[EvidenceRead]:
    """Store consulted URLs as neutral evidence without overstating their claims."""

    hypothesis = await _hypothesis_by_code(session, project_id, hypothesis_code)
    if hypothesis is None:
        raise HypothesisNotFoundError(hypothesis_code)
    if not sources:
        return []

    urls = [item.url for item in sources]
    existing_rows = (
        await session.execute(
            select(Evidence, Hypothesis)
            .join(Hypothesis, Evidence.hypothesis_id == Hypothesis.id)
            .where(
                Evidence.project_id == project_id,
                Evidence.hypothesis_id == hypothesis.id,
                Evidence.url.in_(urls),
            )
        )
    ).all()
    existing_by_url = {
        evidence.url: _evidence_read(evidence, linked_hypothesis.code)
        for evidence, linked_hypothesis in existing_rows
    }

    next_sequence = await _next_evidence_sequence(session, project_id)
    registered: list[EvidenceRead] = []
    seen_domains: set[str] = set()
    for item in sources:
        host = urlsplit(item.url).netloc.casefold().removeprefix("www.")
        if host in seen_domains:
            continue
        seen_domains.add(host)
        existing = existing_by_url.get(item.url)
        if existing is not None:
            registered.append(existing)
            continue
        evidence = Evidence(
            project_id=project_id,
            sequence=next_sequence,
            hypothesis_id=hypothesis.id,
            agent_run_id=agent_run_id,
            origin=EvidenceOrigin.RESEARCHER,
            source=item.title or host or item.url,
            source_type="WEB_SEARCH",
            claim=finding,
            direction=EvidenceDirection.NEUTRAL,
            strength=1,
            epistemic_classification=EpistemicClassification.UNKNOWN,
            url=item.url,
            date=None,
        )
        session.add(evidence)
        await session.flush()
        registered.append(_evidence_read(evidence, hypothesis.code))
        next_sequence += 1
    return registered


async def _require_project(session: AsyncSession, project_id: UUID) -> Project:
    project = await session.get(Project, str(project_id))
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


async def _hypothesis_by_code(
    session: AsyncSession, project_id: str, code: str
) -> Hypothesis | None:
    if len(code) < 4 or not code.startswith("H") or not code[1:].isdigit():
        return None
    sequence = int(code[1:])
    return await session.scalar(
        select(Hypothesis).where(
            Hypothesis.project_id == project_id,
            Hypothesis.sequence == sequence,
        )
    )


async def _next_hypothesis_sequence(
    session: AsyncSession, project_id: str
) -> int:
    current = await session.scalar(
        select(func.max(Hypothesis.sequence)).where(
            Hypothesis.project_id == project_id
        )
    )
    return int(current or 0) + 1


async def _next_evidence_sequence(session: AsyncSession, project_id: str) -> int:
    current = await session.scalar(
        select(func.max(Evidence.sequence)).where(Evidence.project_id == project_id)
    )
    return int(current or 0) + 1


def _hypothesis_read(
    hypothesis: Hypothesis, evidence_ids: list[str]
) -> HypothesisRead:
    return HypothesisRead(
        id=hypothesis.code,
        statement=hypothesis.statement,
        category=hypothesis.category,
        impact=hypothesis.impact,
        confidence=hypothesis.confidence,
        priority=hypothesis.priority,
        status=hypothesis.status,
        epistemic_classification=hypothesis.epistemic_classification,
        evidence_ids=evidence_ids,
        origin=hypothesis.origin,
        source_version_id=hypothesis.source_version_id,
        created_at=hypothesis.created_at,
        updated_at=hypothesis.updated_at,
    )


def _evidence_read(evidence: Evidence, hypothesis_code: str) -> EvidenceRead:
    return EvidenceRead(
        id=evidence.code,
        source=evidence.source,
        source_type=evidence.source_type,
        claim=evidence.claim,
        hypothesis_id=hypothesis_code,
        direction=evidence.direction,
        strength=evidence.strength,
        epistemic_classification=evidence.epistemic_classification,
        url=evidence.url,
        date=evidence.date,
        origin=evidence.origin,
        created_at=evidence.created_at,
    )
