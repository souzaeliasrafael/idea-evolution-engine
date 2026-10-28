from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType
from app.schemas.development import (
    ArchitectureOptionOutput,
    DevelopmentBlueprintOutput,
    ProductDefinitionOutput,
    TechnicalReviewOutput,
)


class ProductArchitectAgent(TypedAgent[ProductDefinitionOutput]):
    role = AgentType.PRODUCT_ARCHITECT
    prompt_name = "product_architect"
    output_schema = ProductDefinitionOutput

    async def run(
        self, *, project_context: dict[str, Any], user_context: str | None
    ) -> AgentResult[ProductDefinitionOutput]:
        return await self.execute(
            {
                "project_context": project_context,
                "user_context": user_context,
                "allowed_evidence_ids": project_context.get(
                    "allowed_evidence_ids", []
                ),
            }
        )

    def validate_output(
        self, output: ProductDefinitionOutput, input_data: dict[str, Any]
    ) -> None:
        _validate_evidence_ids(output.evidence_ids, input_data)


class SolutionArchitectAgent(TypedAgent[ArchitectureOptionOutput]):
    role = AgentType.SOLUTION_ARCHITECT
    prompt_name = "solution_architect"
    output_schema = ArchitectureOptionOutput

    async def run(
        self,
        *,
        project_context: dict[str, Any],
        product_definition: dict[str, Any],
        option_number: int,
        previous_options: list[dict[str, Any]],
        user_context: str | None,
    ) -> AgentResult[ArchitectureOptionOutput]:
        return await self.execute(
            {
                "project_context": project_context,
                "product_definition": product_definition,
                "option_number": option_number,
                "previous_options": previous_options,
                "user_context": user_context,
                "allowed_evidence_ids": project_context.get(
                    "allowed_evidence_ids", []
                ),
            }
        )

    def validate_output(
        self, output: ArchitectureOptionOutput, input_data: dict[str, Any]
    ) -> None:
        _validate_evidence_ids(output.evidence_ids, input_data)
        previous_names = {
            str(item.get("option_name", "")).strip().casefold()
            for item in input_data["previous_options"]
        }
        if output.option_name.casefold() in previous_names:
            raise ValueError("Architecture option must have a distinct name")


class TechnicalCriticAgent(TypedAgent[TechnicalReviewOutput]):
    role = AgentType.TECHNICAL_CRITIC
    prompt_name = "technical_critic"
    output_schema = TechnicalReviewOutput

    async def run(
        self,
        *,
        project_context: dict[str, Any],
        product_definition: dict[str, Any],
        architecture_options: list[dict[str, Any]],
        user_context: str | None,
    ) -> AgentResult[TechnicalReviewOutput]:
        return await self.execute(
            {
                "project_context": project_context,
                "product_definition": product_definition,
                "architecture_options": architecture_options,
                "user_context": user_context,
            }
        )

    def validate_output(
        self, output: TechnicalReviewOutput, input_data: dict[str, Any]
    ) -> None:
        option_names = {
            str(item.get("option_name", "")).strip().casefold()
            for item in input_data["architecture_options"]
        }
        if output.recommended_option.casefold() not in option_names:
            raise ValueError("Technical Critic must recommend an existing option")


class RoadmapPlannerAgent(TypedAgent[DevelopmentBlueprintOutput]):
    role = AgentType.ROADMAP_PLANNER
    prompt_name = "roadmap_planner"
    output_schema = DevelopmentBlueprintOutput

    async def run(
        self,
        *,
        project_context: dict[str, Any],
        product_definition: dict[str, Any],
        architecture_options: list[dict[str, Any]],
        technical_review: dict[str, Any],
        user_context: str | None,
    ) -> AgentResult[DevelopmentBlueprintOutput]:
        return await self.execute(
            {
                "project_context": project_context,
                "product_definition": product_definition,
                "architecture_options": architecture_options,
                "technical_review": technical_review,
                "user_context": user_context,
                "allowed_evidence_ids": project_context.get(
                    "allowed_evidence_ids", []
                ),
            }
        )

    def validate_output(
        self, output: DevelopmentBlueprintOutput, input_data: dict[str, Any]
    ) -> None:
        option_names = {
            str(item.get("option_name", "")).strip().casefold()
            for item in input_data["architecture_options"]
        }
        if output.selected_option.casefold() not in option_names:
            raise ValueError("Roadmap must select an existing architecture option")
        allowed_phases = {item.number for item in output.phases}
        referenced_phases = {
            item.phase for item in output.initial_backlog
        } | {item.delivered_in_phase for item in output.traceability}
        if not referenced_phases.issubset(allowed_phases):
            raise ValueError("Backlog and traceability must reference existing phases")
        for item in output.traceability:
            _validate_evidence_ids(item.evidence_ids, input_data)


def _validate_evidence_ids(ids: list[str], input_data: dict[str, Any]) -> None:
    allowed = set(input_data.get("allowed_evidence_ids", []))
    unknown = set(ids) - allowed
    if unknown:
        raise ValueError(
            "Unknown evidence IDs: " + ", ".join(sorted(unknown))
        )
