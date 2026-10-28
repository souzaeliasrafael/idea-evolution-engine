from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType, EvidenceDirection
from app.llm.base import LLMProvider, LLMRequest, LLMResponse, WebSearchConfig
from app.schemas.research import ResearcherOutput


class ResearcherAgent(TypedAgent[ResearcherOutput]):
    role = AgentType.RESEARCHER
    prompt_name = "researcher"
    output_schema = ResearcherOutput
    prompt_version = "v3"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_attempts: int = 2,
        retry_max_output_tokens: int = 16_384,
        prompt: str | None = None,
        prompt_version: str | None = None,
        web_search: WebSearchConfig | None = None,
    ) -> None:
        self.web_search = web_search
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
        research_target: dict[str, Any],
        hypotheses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        criticisms: list[dict[str, Any]],
        unanswered_questions: list[str],
        accumulated_context: dict[str, Any] | None = None,
        workflow_stage: str = "INDEPENDENT",
        user_context: str | None = None,
    ) -> AgentResult[ResearcherOutput]:
        input_data: dict[str, Any] = {
            "current_concept": current_concept,
            "research_target": research_target,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "criticisms": criticisms,
            "unanswered_questions": unanswered_questions,
            "accumulated_context": accumulated_context or {},
            "workflow_stage": workflow_stage,
        }
        if user_context is not None:
            input_data["user_context"] = user_context
        input_data["web_search_enabled"] = self.web_search is not None
        return await self.execute(input_data)

    def build_request(
        self,
        input_data: dict[str, Any],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMRequest:
        retry_feedback = input_data.get("_retry_feedback")
        web_search = (
            None
            if isinstance(retry_feedback, dict) and retry_feedback.get("web_sources")
            else self.web_search
        )
        return super().build_request(
            input_data,
            max_output_tokens=max_output_tokens,
        ).model_copy(
            update={"web_search": web_search}
        )

    def validate_output(
        self, output: ResearcherOutput, input_data: dict[str, Any]
    ) -> None:
        evidence_by_id = {item["id"]: item for item in input_data["evidence"]}
        referenced_ids = set(output.evidence) | set(output.contradictory_evidence)
        unknown_ids = referenced_ids - set(evidence_by_id)
        if unknown_ids:
            names = ", ".join(sorted(unknown_ids))
            raise ValueError(f"Researcher cited unknown evidence IDs: {names}")

        invalid_contradictions = {
            evidence_id
            for evidence_id in output.contradictory_evidence
            if evidence_by_id[evidence_id]["direction"]
            != EvidenceDirection.CONTRADICT.value
        }
        if invalid_contradictions:
            names = ", ".join(sorted(invalid_contradictions))
            raise ValueError(
                f"Contradictory evidence must have CONTRADICT direction: {names}"
            )
    def validate_response(
        self,
        output: ResearcherOutput,
        input_data: dict[str, Any],
        response: LLMResponse,
    ) -> None:
        referenced_ids = set(output.evidence) | set(output.contradictory_evidence)
        if not referenced_ids and not response.web_sources and output.confidence > 0.20:
            raise ValueError("Research without cited evidence requires confidence <= 0.20")
