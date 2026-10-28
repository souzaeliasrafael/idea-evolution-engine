from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType, DecisionType
from app.llm.base import LLMProvider
from app.schemas.judgment import JudgeAssessment
from app.scoring.engine import ScoreEngine


class JudgeAgent(TypedAgent[JudgeAssessment]):
    role = AgentType.JUDGE
    prompt_name = "judge"
    output_schema = JudgeAssessment
    prompt_version = "v3"

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
        criticisms: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        latest_research: dict[str, Any] | None,
        accumulated_context: dict[str, Any],
        experiments: list[dict[str, Any]],
        previous_scores: list[dict[str, Any]],
        previous_decisions: list[dict[str, Any]],
        stagnation_detected: bool,
        user_context: str | None = None,
    ) -> AgentResult[JudgeAssessment]:
        input_data: dict[str, Any] = {
            "current_concept": current_concept,
            "criticisms": criticisms,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "latest_research": latest_research,
            "accumulated_context": accumulated_context,
            "experiments": experiments,
            "previous_scores": previous_scores,
            "previous_decisions": previous_decisions,
            "stagnation_detected": stagnation_detected,
        }
        if user_context is not None:
            input_data["user_context"] = user_context
        return await self.execute(input_data)

    def validate_output(
        self, output: JudgeAssessment, input_data: dict[str, Any]
    ) -> None:
        calculation = ScoreEngine.calculate(output.criteria)
        if input_data["stagnation_detected"] and output.decision == DecisionType.REFINE:
            raise ValueError(
                "REFINE is not allowed after stagnation; choose PIVOT, TEST, "
                "RESEARCH, APPROVE, or DISCARD"
            )
        if output.decision == DecisionType.APPROVE:
            if calculation.total_score < 80:
                raise ValueError("APPROVE requires score >= 80")
            if output.confidence < 0.70:
                raise ValueError("APPROVE requires confidence >= 0.70")
            if output.critical_blockers:
                raise ValueError("APPROVE requires zero critical blockers")
