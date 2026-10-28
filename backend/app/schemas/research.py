from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


NonBlankText = Annotated[str, Field(min_length=1)]
EvidenceCode = Annotated[str, Field(pattern=r"^E[0-9]{3,}$")]


class ResearcherOutput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: NonBlankText
    finding: NonBlankText
    evidence: list[EvidenceCode]
    confidence: float = Field(ge=0.0, le=1.0)
    contradictory_evidence: list[EvidenceCode]
    impact_on_project: NonBlankText
    recommended_action: NonBlankText
