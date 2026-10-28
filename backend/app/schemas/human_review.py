from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import HumanReviewAction


class HumanReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    action: HumanReviewAction
    note: Annotated[str, Field(min_length=1, max_length=5000)] | None = None

    @model_validator(mode="after")
    def require_manual_pivot_note(self) -> "HumanReviewRequest":
        if self.action == HumanReviewAction.MANUAL_PIVOT and self.note is None:
            raise ValueError("MANUAL_PIVOT requires a note with pivot instructions")
        return self
