from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DevelopmentBlueprintStatus


ShortText = Annotated[str, Field(min_length=1, max_length=2000)]
EvidenceCode = Annotated[str, Field(pattern=r"^E[0-9]{3,}$")]


class FunctionalRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^FR-[0-9]{3}$")]
    description: ShortText
    priority: Literal["MUST", "SHOULD", "COULD"]
    acceptance_criteria: list[ShortText] = Field(min_length=1, max_length=6)


class NonFunctionalRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^NFR-[0-9]{3}$")]
    category: Annotated[str, Field(min_length=1, max_length=100)]
    requirement: ShortText
    measurable_target: ShortText


class ProductDefinitionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    executive_summary: ShortText
    goals: list[ShortText] = Field(min_length=1, max_length=10)
    non_goals: list[ShortText] = Field(max_length=10)
    target_users: list[ShortText] = Field(min_length=1, max_length=10)
    core_use_cases: list[ShortText] = Field(min_length=1, max_length=12)
    functional_requirements: list[FunctionalRequirement] = Field(
        min_length=1, max_length=30
    )
    non_functional_requirements: list[NonFunctionalRequirement] = Field(
        min_length=1, max_length=20
    )
    constraints: list[ShortText] = Field(max_length=15)
    open_questions: list[ShortText] = Field(max_length=15)
    evidence_ids: list[EvidenceCode] = Field(max_length=50)


class TechnologyChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    layer: Annotated[str, Field(min_length=1, max_length=100)]
    technology: Annotated[str, Field(min_length=1, max_length=200)]
    rationale: ShortText


class ArchitectureComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=150)]
    responsibility: ShortText
    interfaces: list[ShortText] = Field(max_length=8)
    data_owned: list[ShortText] = Field(max_length=8)


class ArchitectureOptionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    option_name: Annotated[str, Field(min_length=1, max_length=150)]
    summary: ShortText
    system_style: Annotated[str, Field(min_length=1, max_length=300)]
    technology_stack: list[TechnologyChoice] = Field(min_length=1, max_length=15)
    components: list[ArchitectureComponent] = Field(min_length=1, max_length=20)
    data_flows: list[ShortText] = Field(min_length=1, max_length=15)
    api_contracts: list[ShortText] = Field(max_length=15)
    data_model: list[ShortText] = Field(max_length=15)
    security_controls: list[ShortText] = Field(min_length=1, max_length=15)
    infrastructure: list[ShortText] = Field(min_length=1, max_length=15)
    observability: list[ShortText] = Field(min_length=1, max_length=12)
    deployment_strategy: ShortText
    tradeoffs: list[ShortText] = Field(min_length=1, max_length=12)
    risks: list[ShortText] = Field(max_length=12)
    evidence_ids: list[EvidenceCode] = Field(max_length=50)


class OptionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    option_name: Annotated[str, Field(min_length=1, max_length=150)]
    strengths: list[ShortText] = Field(min_length=1, max_length=8)
    weaknesses: list[ShortText] = Field(min_length=1, max_length=8)
    delivery_risk: int = Field(ge=1, le=10)
    suitability: int = Field(ge=1, le=10)


class TechnicalFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    category: Annotated[str, Field(min_length=1, max_length=100)]
    issue: ShortText
    impact: ShortText
    mitigation: ShortText


class TechnicalReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recommended_option: Annotated[str, Field(min_length=1, max_length=150)]
    recommendation_reason: ShortText
    option_assessments: list[OptionAssessment] = Field(min_length=1, max_length=3)
    findings: list[TechnicalFinding] = Field(max_length=25)
    required_changes: list[ShortText] = Field(max_length=15)
    unresolved_risks: list[ShortText] = Field(max_length=15)


class DeliveryPhase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: int = Field(ge=1, le=12)
    name: Annotated[str, Field(min_length=1, max_length=150)]
    objective: ShortText
    deliverables: list[ShortText] = Field(min_length=1, max_length=12)
    dependencies: list[ShortText] = Field(max_length=10)
    acceptance_criteria: list[ShortText] = Field(min_length=1, max_length=10)


class BacklogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^BL-[0-9]{3}$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: ShortText
    phase: int = Field(ge=1, le=12)
    priority: Literal["MUST", "SHOULD", "COULD"]
    acceptance_criteria: list[ShortText] = Field(min_length=1, max_length=6)


class TraceabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: Annotated[str, Field(pattern=r"^(FR|NFR)-[0-9]{3}$")]
    evidence_ids: list[EvidenceCode] = Field(max_length=20)
    delivered_in_phase: int = Field(ge=1, le=12)


class DevelopmentBlueprintOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selected_option: Annotated[str, Field(min_length=1, max_length=150)]
    decision_rationale: ShortText
    architecture_adjustments: list[ShortText] = Field(max_length=15)
    phases: list[DeliveryPhase] = Field(min_length=1, max_length=12)
    initial_backlog: list[BacklogItem] = Field(min_length=1, max_length=40)
    testing_strategy: list[ShortText] = Field(min_length=1, max_length=15)
    security_plan: list[ShortText] = Field(min_length=1, max_length=15)
    deployment_plan: list[ShortText] = Field(min_length=1, max_length=15)
    observability_plan: list[ShortText] = Field(min_length=1, max_length=15)
    operational_plan: list[ShortText] = Field(min_length=1, max_length=15)
    traceability: list[TraceabilityItem] = Field(max_length=50)
    risks: list[ShortText] = Field(max_length=20)
    unresolved_questions: list[ShortText] = Field(max_length=20)


class DevelopmentBlueprintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    architecture_alternatives: int = Field(default=2, ge=1, le=3)
    user_context: Annotated[str, Field(max_length=20_000)] | None = None
    max_ai_budget: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=6
    )


class DevelopmentBlueprintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version: int
    status: DevelopmentBlueprintStatus
    architecture_alternatives: int
    user_context: str | None
    max_ai_budget: Decimal | None
    estimated_cost: Decimal
    product_definition: ProductDefinitionOutput | None
    architecture_options: list[ArchitectureOptionOutput]
    technical_review: TechnicalReviewOutput | None
    final_blueprint: DevelopmentBlueprintOutput | None
    agent_run_ids: list[str]
    error: str | None
    created_at: datetime
    completed_at: datetime | None
