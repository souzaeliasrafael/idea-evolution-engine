from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DecisionType, OrchestratorStopReason


class JudgeChatTurnCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    input_mode: Literal["TEXT", "VOICE"] = "TEXT"


class JudgeChatTurnRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    decision_id: UUID | None
    user_message: str
    input_mode: Literal["TEXT", "VOICE"]
    status: Literal[
        "RUNNING",
        "COMPLETED",
        "NO_DECISION",
        "CANCELLED",
        "BUDGET_STOPPED",
        "FAILED",
    ]
    requested_rounds: int = Field(ge=1)
    judge_response: str | None
    stop_reason: OrchestratorStopReason | None
    error: str | None
    decision: DecisionType | None
    score: int | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    cost_before: Decimal = Field(ge=0)
    cost_after: Decimal = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None


class JudgeVoiceSessionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_secret: str
    expires_at: int | None = None
    model: str
    voice: str
    max_duration_seconds: int = Field(ge=60, le=3600)
