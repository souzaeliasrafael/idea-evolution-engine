from app.domain.enums import ProjectStatus
from app.services.errors import ProjectTerminalError, RoundLimitExceededError


DEFAULT_ROUNDS_PER_RUN = 3
TERMINAL_PROJECT_STATUSES = frozenset(
    {ProjectStatus.APPROVED, ProjectStatus.DISCARDED}
)


def validate_round_limit(requested: int, configured_maximum: int) -> None:
    if requested < 1:
        raise RoundLimitExceededError("At least one round is required")
    if requested > configured_maximum:
        raise RoundLimitExceededError(
            f"Requested {requested} rounds; configured maximum is {configured_maximum}"
        )


def require_non_terminal_project(status: ProjectStatus) -> None:
    if status in TERMINAL_PROJECT_STATUSES:
        raise ProjectTerminalError(f"Project is already terminal: {status.value}")
