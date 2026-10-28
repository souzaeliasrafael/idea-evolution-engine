from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import get_settings
from app.database.session import get_db_session
from app.domain.enums import AgentType
from app.llm.router import config_for_agent
from app.schemas.operations import (
    HealthRead,
    ProjectBackup,
    ProjectEfficiencyRead,
    ProjectMetricsRead,
    ProjectReportRead,
    ProviderDiagnostic,
    SystemConfigRead,
)
from app.schemas.project import ProjectRead
from app.services import backups, metrics, reports
from app.services.errors import BackupValidationError, ProjectNotFoundError


router = APIRouter(tags=["operations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/health", response_model=HealthRead)
async def health() -> HealthRead:
    settings = get_settings()
    return HealthRead(
        status="ok",
        version=__version__,
        database=make_url(settings.database_url).get_backend_name(),
    )


@router.get("/ready", response_model=HealthRead)
async def readiness(session: DatabaseSession) -> HealthRead:
    settings = get_settings()
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from exc
    return HealthRead(
        status="ready",
        version=__version__,
        database=make_url(settings.database_url).get_backend_name(),
    )


@router.get("/system/config", response_model=SystemConfigRead)
async def safe_configuration() -> SystemConfigRead:
    settings = get_settings()
    providers = []
    for agent in AgentType:
        config = config_for_agent(settings, agent)
        providers.append(
            ProviderDiagnostic(
                agent=agent,
                provider=config.provider,
                model=config.model,
                input_cost_per_million=config.input_cost_per_million,
                cached_input_cost_per_million=config.cached_input_cost_per_million,
                output_cost_per_million=config.output_cost_per_million,
                credential_configured=_credential_configured(
                    settings, config.provider
                ),
                pricing_configured=(
                    config.input_cost_per_million > 0
                    or config.output_cost_per_million > 0
                    or config.provider.lower()
                    in {"mock", "local", "compatible", "openai-compatible", "openai_compatible"}
                ),
            )
        )
    return SystemConfigRead(
        app_name=settings.app_name,
        app_env=settings.app_env,
        max_rounds=settings.max_rounds,
        max_attempts=settings.llm_max_attempts,
        max_output_tokens=settings.llm_max_output_tokens,
        builder_max_output_tokens=settings.builder_max_output_tokens,
        adaptive_agent_depth_enabled=settings.adaptive_agent_depth_enabled,
        adaptive_depth_score_threshold=settings.adaptive_depth_score_threshold,
        adaptive_depth_confidence_threshold=(
            settings.adaptive_depth_confidence_threshold
        ),
        research_web_enabled=settings.research_web_enabled,
        research_web_max_calls=settings.research_web_max_calls,
        research_web_context_size=settings.research_web_context_size,
        web_search_cost_per_call=settings.openai_web_search_cost_per_call,
        providers=providers,
    )


@router.get("/projects/{project_id}/metrics", response_model=ProjectMetricsRead)
async def project_metrics(
    project_id: UUID, session: DatabaseSession
) -> ProjectMetricsRead:
    try:
        return await metrics.project_metrics(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/projects/{project_id}/efficiency", response_model=ProjectEfficiencyRead)
async def project_efficiency(
    project_id: UUID, session: DatabaseSession
) -> ProjectEfficiencyRead:
    try:
        return await metrics.project_efficiency(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/projects/{project_id}/report", response_model=ProjectReportRead)
async def project_report(
    project_id: UUID, session: DatabaseSession
) -> ProjectReportRead:
    try:
        return await reports.build_report(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/projects/{project_id}/report.md")
async def project_report_markdown(
    project_id: UUID, session: DatabaseSession
) -> Response:
    try:
        report = await reports.build_report(session, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    filename = quote(f"{report.project.name}-report.md")
    return Response(
        content=reports.render_markdown(report),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/projects/{project_id}/backup", response_model=ProjectBackup)
async def backup_project(
    project_id: UUID, session: DatabaseSession, response: Response
) -> ProjectBackup:
    try:
        backup = await backups.export_project(session, project_id)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="project-{project_id}-backup.json"'
        )
        return backup
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post(
    "/projects/import", response_model=ProjectRead, status_code=status.HTTP_201_CREATED
)
async def restore_project(
    payload: ProjectBackup, session: DatabaseSession
) -> ProjectRead:
    try:
        return await backups.import_project(session, payload)
    except BackupValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _credential_configured(settings: object, provider: str) -> bool:
    normalized = provider.strip().lower()
    if normalized in {
        "mock",
        "local",
        "compatible",
        "openai-compatible",
        "openai_compatible",
    }:
        return True
    attribute = {
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "gemini": "gemini_api_key",
    }.get(normalized)
    if attribute is None:
        return False
    secret = getattr(settings, attribute, None)
    getter = getattr(secret, "get_secret_value", None)
    return bool(getter()) if callable(getter) else False
