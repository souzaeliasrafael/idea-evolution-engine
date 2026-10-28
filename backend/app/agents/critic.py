from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType
from app.llm.base import LLMProvider
from app.schemas.evaluation import CriticOutput


class CriticAgent(TypedAgent[CriticOutput]):
    role = AgentType.CRITIC
    prompt_name = "critic"
    output_schema = CriticOutput

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_attempts: int = 2,
        retry_max_output_tokens: int = 16_384,
        prompt: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        super().__init__(
            provider,
            max_attempts=max_attempts,
            retry_max_output_tokens=retry_max_output_tokens,
            prompt=prompt,
            prompt_version=prompt_version,
        )

    async def run(
        self,
        *,
        current_concept: dict[str, Any],
        hypotheses: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        accumulated_context: dict[str, Any] | None = None,
        user_context: str | None = None,
    ) -> AgentResult[CriticOutput]:
        input_data: dict[str, Any] = {
            "current_concept": current_concept,
            "hypotheses": hypotheses or [],
            "evidence": evidence or [],
            "accumulated_context": accumulated_context or {},
        }
        if user_context is not None:
            input_data["user_context"] = user_context
        return await self.execute(input_data)

    def validate_output(
        self, output: CriticOutput, input_data: dict[str, Any]
    ) -> None:
        del output, input_data
