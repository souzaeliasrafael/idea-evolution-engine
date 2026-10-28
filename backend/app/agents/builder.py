import json
import re
from typing import Any

from app.agents.base import AgentRecovery, AgentResult, TypedAgent
from app.domain.enums import AgentType
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.schemas.evaluation import BuilderOutput


BUILDER_RESPONSE_GUARD = """

Mandatory response budget: be concise; use no more than 6 items in each
top-level list and 8 items in each concept list. Use one short sentence per
item, avoid repetition, and keep long concept fields below 2,000 characters.
Return only one complete JSON object matching the schema.
""".strip()


class BuilderAgent(TypedAgent[BuilderOutput]):
    role = AgentType.BUILDER
    prompt_name = "builder"
    output_schema = BuilderOutput
    prompt_version = "v4"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_attempts: int = 2,
        retry_max_output_tokens: int = 16_384,
        initial_max_output_tokens: int = 8_192,
        prompt: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        super().__init__(
            provider,
            max_attempts=max_attempts,
            retry_max_output_tokens=retry_max_output_tokens,
            initial_max_output_tokens=initial_max_output_tokens,
            retry_on_max_output_tokens=False,
            prompt=prompt,
            prompt_version=prompt_version,
        )
        if "Mandatory response budget:" not in self.prompt:
            self.prompt = f"{self.prompt.rstrip()}\n\n{BUILDER_RESPONSE_GUARD}"

    async def run(
        self,
        *,
        current_concept: dict[str, Any],
        previous_criticisms: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        accumulated_context: dict[str, Any] | None = None,
        workflow_stage: str = "INDEPENDENT",
        workflow_instruction: dict[str, Any] | None = None,
        user_context: str | None = None,
    ) -> AgentResult[BuilderOutput]:
        input_data: dict[str, Any] = {
            "current_concept": current_concept,
            "previous_criticisms": previous_criticisms,
            "hypotheses": hypotheses or [],
            "evidence": evidence or [],
            "accumulated_context": accumulated_context or {},
            "workflow_stage": workflow_stage,
            "workflow_instruction": workflow_instruction,
        }
        if user_context is not None:
            input_data["user_context"] = user_context
        return await self.execute(input_data)

    async def recover_truncated_response(
        self, input_data: dict[str, Any], response: LLMResponse
    ) -> AgentRecovery[BuilderOutput] | None:
        top_fields = {
            "improvements": _array_schema(6),
            "problems_solved": _array_schema(6),
            "unresolved_problems": _array_schema(6),
            "new_hypotheses": _array_schema(6),
            "proposed_changes": _array_schema(6),
        }
        concept_fields = {
            "title": _string_schema(200),
            "problem": _string_schema(2000),
            "solution": _string_schema(2000),
            "target_users": _array_schema(8),
            "value_proposition": _string_schema(2000),
            "possible_use_cases": _array_schema(8),
            "business_models": _array_schema(8),
            "technical_assumptions": _array_schema(8),
            "business_assumptions": _array_schema(8),
            "unknowns": _array_schema(8),
            "risks": _array_schema(8),
            "initial_mvp": _string_schema(2000),
        }
        salvaged_top = {
            field: value
            for field in top_fields
            if (value := _extract_complete_value(response.content, field)) is not None
        }
        salvaged_concept = {
            field: value
            for field in concept_fields
            if (value := _extract_complete_value(response.content, field)) is not None
        }
        missing_schemas = {
            **{
                field: schema
                for field, schema in top_fields.items()
                if field not in salvaged_top
            },
            **{
                f"new_concept__{field}": schema
                for field, schema in concept_fields.items()
                if field not in salvaged_concept
            },
        }
        recovery_response: LLMResponse | None = None
        recovered_values: dict[str, Any] = {}
        if missing_schemas:
            recovery_response = await self.provider.generate(
                LLMRequest(
                    role=self.role.value,
                    prompt=(
                        "Recover only the listed missing fields from a Builder response "
                        "that was cut off. Do not rewrite fields already salvaged. Be "
                        "concise, preserve the original idea, and return only the typed "
                        "JSON object requested by the schema."
                    ),
                    input_data={
                        "current_concept": input_data["current_concept"],
                        "missing_fields": list(missing_schemas),
                        "salvaged_fields": {
                            **salvaged_top,
                            "new_concept": salvaged_concept,
                        },
                        "truncated_response": response.content[-24_000:],
                    },
                    output_schema_name="builder_missing_fields",
                    output_schema={
                        "type": "object",
                        "properties": {
                            "values": {
                                "type": "object",
                                "properties": missing_schemas,
                                "required": list(missing_schemas),
                                "additionalProperties": False,
                            }
                        },
                        "required": ["values"],
                        "additionalProperties": False,
                    },
                    max_output_tokens=4096,
                )
            )
            if recovery_response.finish_reason is not None:
                raise ValueError(
                    "Builder partial recovery was not completed: "
                    f"{recovery_response.finish_reason}"
                )
            decoded = json.loads(recovery_response.content)
            recovered_values = decoded["values"]

        for field in top_fields:
            if field not in salvaged_top:
                salvaged_top[field] = recovered_values[field]
        for field in concept_fields:
            if field not in salvaged_concept:
                salvaged_concept[field] = recovered_values[f"new_concept__{field}"]
        merged = {**salvaged_top, "new_concept": salvaged_concept}
        output = self.output_schema.model_validate(merged)
        self.validate_output(output, input_data)
        return AgentRecovery(
            output=output,
            response=recovery_response,
            output_json=output.model_dump(mode="json"),
        )


def _extract_complete_value(raw: str, field: str) -> Any | None:
    match = re.search(rf'"{re.escape(field)}"\s*:', raw)
    if match is None:
        return None
    remainder = raw[match.end() :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(remainder)
    except json.JSONDecodeError:
        return None
    return value


def _string_schema(max_length: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


def _array_schema(max_items: int) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _string_schema(600),
        "maxItems": max_items,
    }
