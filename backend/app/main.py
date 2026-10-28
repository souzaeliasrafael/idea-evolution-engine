from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.api.profiles import router as profiles_router
from app.api.operations import router as operations_router
from app.api.prompts import router as prompts_router
from app.api.finance import router as finance_router
from app.api.development import router as development_router
from app.api.discovery import router as discovery_router
from app.api.discovery_prompts import router as discovery_prompts_router
from app import __version__
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Bounded idea evaluation API with cost controls, stagnation detection, "
            "traceable evidence, and a multi-agent workflow."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(projects_router)
    application.include_router(profiles_router)
    application.include_router(operations_router)
    application.include_router(prompts_router)
    application.include_router(finance_router)
    application.include_router(development_router)
    application.include_router(discovery_router)
    application.include_router(discovery_prompts_router)
    return application


app = create_app()
