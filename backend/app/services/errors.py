class ProjectNotFoundError(LookupError):
    pass


class ProjectNotStructuredError(RuntimeError):
    pass


class ProjectNotEvaluatedError(RuntimeError):
    pass


class ProjectAlreadyStructuredError(RuntimeError):
    pass


class AgentExecutionFailedError(RuntimeError):
    def __init__(
        self,
        project_id: object,
        *,
        agent: str = "AGENT",
        attempts: int = 0,
        last_error: str | None = None,
    ) -> None:
        self.project_id = str(project_id)
        self.agent = agent
        self.attempts = attempts
        self.last_error = last_error
        suffix = f": {last_error}" if last_error else ""
        super().__init__(
            f"{agent} failed after {attempts or 'all configured'} attempts{suffix}"
        )


class OrchestratorAlreadyRunningError(RuntimeError):
    pass


class WorkflowCancellationRequested(RuntimeError):
    pass


class ProjectTerminalError(RuntimeError):
    pass


class RoundLimitExceededError(ValueError):
    pass


class BudgetLimitReachedError(RuntimeError):
    pass


class HypothesisNotFoundError(LookupError):
    pass


class HypothesisAlreadyExistsError(RuntimeError):
    pass


class DecisionNotFoundError(LookupError):
    pass


class HumanReviewNotPendingError(RuntimeError):
    pass


class PendingHumanReviewError(RuntimeError):
    pass


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentValidationError(ValueError):
    pass


class PendingExperimentError(RuntimeError):
    pass


class AgentProfileNotFoundError(LookupError):
    pass


class AgentProfileAlreadyExistsError(RuntimeError):
    pass


class AgentProfileInvalidError(ValueError):
    pass


class BackupValidationError(ValueError):
    pass


class BillingSyncError(RuntimeError):
    pass


class DevelopmentBlueprintAlreadyRunningError(RuntimeError):
    pass
