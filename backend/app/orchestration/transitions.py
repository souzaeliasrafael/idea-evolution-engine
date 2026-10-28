from dataclasses import dataclass

from app.domain.enums import DecisionType, OrchestratorStopReason, ProjectStatus


@dataclass(frozen=True)
class WorkflowTransition:
    project_status: ProjectStatus
    continue_run: bool
    stop_reason: OrchestratorStopReason | None


TRANSITIONS = {
    DecisionType.REFINE: WorkflowTransition(
        project_status=ProjectStatus.DEBATING,
        continue_run=True,
        stop_reason=None,
    ),
    DecisionType.RESEARCH: WorkflowTransition(
        project_status=ProjectStatus.RESEARCHING,
        continue_run=True,
        stop_reason=None,
    ),
    DecisionType.TEST: WorkflowTransition(
        project_status=ProjectStatus.VALIDATING,
        continue_run=False,
        stop_reason=OrchestratorStopReason.AWAITING_TEST,
    ),
    DecisionType.PIVOT: WorkflowTransition(
        project_status=ProjectStatus.AWAITING_CONFIRMATION,
        continue_run=False,
        stop_reason=OrchestratorStopReason.AWAITING_CONFIRMATION,
    ),
    DecisionType.APPROVE: WorkflowTransition(
        project_status=ProjectStatus.AWAITING_CONFIRMATION,
        continue_run=False,
        stop_reason=OrchestratorStopReason.AWAITING_CONFIRMATION,
    ),
    DecisionType.DISCARD: WorkflowTransition(
        project_status=ProjectStatus.AWAITING_CONFIRMATION,
        continue_run=False,
        stop_reason=OrchestratorStopReason.AWAITING_CONFIRMATION,
    ),
}


def transition_for(decision: DecisionType) -> WorkflowTransition:
    return TRANSITIONS[decision]


def status_for_round_start(
    previous_decision: DecisionType | None,
) -> ProjectStatus:
    if previous_decision == DecisionType.PIVOT:
        return ProjectStatus.PIVOTING
    if previous_decision == DecisionType.RESEARCH:
        return ProjectStatus.RESEARCHING
    return ProjectStatus.DEBATING
