from __future__ import annotations

from datetime import date as DateValue, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    EpistemicClassification,
    EvidenceDirection,
    EvidenceOrigin,
    HypothesisOrigin,
    HypothesisStatus,
)


NonBlankText = Annotated[str, Field(min_length=1)]
HypothesisCode = Annotated[str, Field(pattern=r"^H[0-9]{3,}$")]


class HypothesisCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    statement: NonBlankText
    category: Annotated[str, Field(min_length=1, max_length=100)]
    impact: int = Field(ge=1, le=10)
    confidence: float = Field(ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.OPEN
    epistemic_classification: EpistemicClassification = (
        EpistemicClassification.ASSUMPTION
    )


class HypothesisRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: HypothesisCode
    statement: str
    category: str
    impact: int = Field(ge=1, le=10)
    confidence: float = Field(ge=0.0, le=1.0)
    priority: float = Field(ge=0.0, le=10.0)
    status: HypothesisStatus
    epistemic_classification: EpistemicClassification
    evidence_ids: list[str]
    origin: HypothesisOrigin
    source_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class HypothesisUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact: int | None = Field(default=None, ge=1, le=10)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: HypothesisStatus | None = None
    epistemic_classification: EpistemicClassification | None = None

    @model_validator(mode="after")
    def require_change(self) -> "HypothesisUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one hypothesis field must be supplied")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Hypothesis fields cannot be null")
        return self


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    hypothesis_id: HypothesisCode
    source: NonBlankText
    source_type: Annotated[str, Field(min_length=1, max_length=100)]
    claim: NonBlankText
    direction: EvidenceDirection
    strength: int = Field(ge=0, le=5)
    epistemic_classification: EpistemicClassification = (
        EpistemicClassification.UNKNOWN
    )
    url: str = ""
    date: DateValue | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: Annotated[str, Field(pattern=r"^E[0-9]{3,}$")]
    source: str
    source_type: str
    claim: str
    hypothesis_id: HypothesisCode
    direction: EvidenceDirection
    strength: int = Field(ge=0, le=5)
    epistemic_classification: EpistemicClassification
    url: str
    date: DateValue | None
    origin: EvidenceOrigin
    created_at: datetime
