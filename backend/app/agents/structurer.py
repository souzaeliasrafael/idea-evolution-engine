from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType
from app.llm.base import LLMProvider
from app.schemas.idea import IdeaConcept


class IdeaStructurer(TypedAgent[IdeaConcept]):
    role = AgentType.STRUCTURER
    prompt_name = "structurer"
    output_schema = IdeaConcept

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
        self, *, project_name: str, raw_idea: str
    ) -> AgentResult[IdeaConcept]:
        input_data = {"project_name": project_name, "raw_idea": raw_idea}
        return await self.execute(input_data)

    def validate_output(
        self, output: IdeaConcept, input_data: dict[str, Any]
    ) -> None:
        if output.raw_idea != input_data["raw_idea"]:
            raise ValueError("Structurer must preserve raw_idea exactly")
