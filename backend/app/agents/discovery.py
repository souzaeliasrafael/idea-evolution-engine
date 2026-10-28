from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import DiscoveryAgentType
from app.llm.base import LLMProvider, LLMRequest, WebSearchConfig
from app.schemas.discovery import (
    OpportunityGeneratorOutput,
    OpportunityResearchOutput,
    OpportunityScoutOutput,
    PortfolioJudgeOutput,
)


class OpportunityScoutAgent(TypedAgent[OpportunityScoutOutput]):
    role = DiscoveryAgentType.OPPORTUNITY_SCOUT  # type: ignore[assignment]
    prompt_name = "opportunity_scout"
    output_schema = OpportunityScoutOutput

    def __init__(self, provider: LLMProvider, *, prompt: str | None = None, prompt_version: str | None = None) -> None:
        self.web_search = (
            WebSearchConfig(max_calls=3, context_size="medium")
            if provider.supports_web_search
            else None
        )
        super().__init__(provider, max_attempts=2, initial_max_output_tokens=8_192, prompt=prompt, prompt_version=prompt_version)

    async def run(self, *, founder: dict[str, Any], campaign: dict[str, Any]) -> AgentResult[OpportunityScoutOutput]:
        return await self.execute({"founder": founder, "campaign": campaign})

    def build_request(self, input_data: dict[str, Any], *, max_output_tokens: int | None = None) -> LLMRequest:
        retry_feedback = input_data.get("_retry_feedback")
        web_search = None if isinstance(retry_feedback, dict) and retry_feedback.get("web_sources") else self.web_search
        return super().build_request(input_data, max_output_tokens=max_output_tokens).model_copy(
            update={"web_search": web_search}
        )


class IdeaGeneratorAgent(TypedAgent[OpportunityGeneratorOutput]):
    role = DiscoveryAgentType.IDEA_GENERATOR  # type: ignore[assignment]
    prompt_name = "idea_generator"
    output_schema = OpportunityGeneratorOutput

    def __init__(self, provider: LLMProvider, *, prompt: str | None = None, prompt_version: str | None = None) -> None:
        super().__init__(provider, max_attempts=2, initial_max_output_tokens=8_192, prompt=prompt, prompt_version=prompt_version)

    async def run(
        self,
        *,
        founder: dict[str, Any],
        campaign: dict[str, Any],
        signals: list[dict[str, Any]],
        opportunity_memory: dict[str, Any],
    ) -> AgentResult[OpportunityGeneratorOutput]:
        return await self.execute({
            "founder": founder,
            "campaign": campaign,
            "signals": signals,
            "opportunity_memory": opportunity_memory,
        })

    def validate_output(self, output: OpportunityGeneratorOutput, input_data: dict[str, Any]) -> None:
        target = int(input_data["campaign"]["candidate_target"])
        if not 3 <= len(output.opportunities) <= target:
            raise ValueError(f"Generator must return between 3 and {target} opportunities")
        known = {item["code"] for item in input_data["signals"]}
        unknown = {code for item in output.opportunities for code in item.signal_codes} - known
        if unknown:
            raise ValueError(f"Unknown opportunity signal codes: {', '.join(sorted(unknown))}")
        known_candidates = {
            item["candidate_id"] for item in input_data["opportunity_memory"]["items"]
        }
        # Lineage is useful metadata, but a hallucinated UUID must not discard
        # an otherwise valid paid generation. Keep only references that were
        # actually present in the compact memory supplied to this call.
        for item in output.opportunities:
            item.inspired_by_candidate_ids = [
                candidate_id
                for candidate_id in item.inspired_by_candidate_ids
                if candidate_id in known_candidates
            ]


class OpportunityResearcherAgent(TypedAgent[OpportunityResearchOutput]):
    role = DiscoveryAgentType.OPPORTUNITY_RESEARCHER  # type: ignore[assignment]
    prompt_name = "opportunity_researcher"
    output_schema = OpportunityResearchOutput

    def __init__(self, provider: LLMProvider, *, prompt: str | None = None, prompt_version: str | None = None) -> None:
        self.web_search = (
            WebSearchConfig(max_calls=3, context_size="medium")
            if provider.supports_web_search
            else None
        )
        super().__init__(provider, max_attempts=2, initial_max_output_tokens=12_288, prompt=prompt, prompt_version=prompt_version)

    async def run(
        self,
        *,
        founder: dict[str, Any],
        campaign: dict[str, Any],
        signals: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
    ) -> AgentResult[OpportunityResearchOutput]:
        return await self.execute(
            {"founder": founder, "campaign": campaign, "signals": signals, "candidates": candidates}
        )

    def build_request(self, input_data: dict[str, Any], *, max_output_tokens: int | None = None) -> LLMRequest:
        retry_feedback = input_data.get("_retry_feedback")
        web_search = None if isinstance(retry_feedback, dict) and retry_feedback.get("web_sources") else self.web_search
        return super().build_request(input_data, max_output_tokens=max_output_tokens).model_copy(
            update={"web_search": web_search}
        )

    def validate_output(self, output: OpportunityResearchOutput, input_data: dict[str, Any]) -> None:
        expected = {item["id"] for item in input_data["candidates"]}
        received = {item.candidate_id for item in output.analyses}
        if received != expected:
            raise ValueError("Research must return exactly one analysis for every shortlisted candidate")
        for analysis in output.analyses:
            purchase_evidence = [
                item
                for item in (*analysis.demand_evidence, *analysis.competitor_evidence)
                if item.supports_purchase_behavior
            ]
            if analysis.direct_purchase_evidence and not purchase_evidence:
                raise ValueError(
                    "direct_purchase_evidence requires at least one source that supports purchase behavior"
                )


class PortfolioJudgeAgent(TypedAgent[PortfolioJudgeOutput]):
    role = DiscoveryAgentType.PORTFOLIO_JUDGE  # type: ignore[assignment]
    prompt_name = "portfolio_judge"
    output_schema = PortfolioJudgeOutput

    def __init__(self, provider: LLMProvider, *, prompt: str | None = None, prompt_version: str | None = None) -> None:
        super().__init__(provider, max_attempts=2, initial_max_output_tokens=7_000, prompt=prompt, prompt_version=prompt_version)

    async def run(
        self,
        *,
        founder: dict[str, Any],
        campaign: dict[str, Any],
        candidates: list[dict[str, Any]],
        opportunity_memory: dict[str, Any],
    ) -> AgentResult[PortfolioJudgeOutput]:
        return await self.execute({
            "founder": founder,
            "campaign": campaign,
            "candidates": candidates,
            "opportunity_memory": opportunity_memory,
        })

    def validate_output(self, output: PortfolioJudgeOutput, input_data: dict[str, Any]) -> None:
        expected = {item["id"] for item in input_data["candidates"]}
        received = {item.candidate_id for item in output.evaluations}
        if received != expected:
            raise ValueError("Judge must return exactly one evaluation for every researched candidate")
        known_tags = set(input_data["opportunity_memory"].get("rejected_tag_counts", {}))
        unknown_tags = {
            tag
            for item in output.evaluations
            for tag in item.matched_rejection_tags
            if tag not in known_tags
        }
        if unknown_tags:
            raise ValueError("Judge returned rejection tags that are not in founder memory")
