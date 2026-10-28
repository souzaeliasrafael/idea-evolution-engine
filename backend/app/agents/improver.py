from typing import Any

from app.agents.base import AgentResult, TypedAgent
from app.domain.enums import AgentType, ScoreCriterion
from app.schemas.improvement import ImprovementPlanOutput


class ImproverAgent(TypedAgent[ImprovementPlanOutput]):
    role = AgentType.IMPROVER
    prompt_name = "improver"
    output_schema = ImprovementPlanOutput
    prompt_version = "v1"

    async def run(
        self,
        *,
        current_concept: dict[str, Any],
        latest_score: dict[str, Any],
        latest_decision: dict[str, Any],
        criticisms: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        latest_research: dict[str, Any] | None,
        score_history: list[dict[str, Any]],
        previous_plans: list[dict[str, Any]],
        user_context: str | None = None,
    ) -> AgentResult[ImprovementPlanOutput]:
        input_data: dict[str, Any] = {
            "current_concept": current_concept,
            "latest_score": latest_score,
            "latest_decision": latest_decision,
            "criticisms": criticisms,
            "hypotheses": hypotheses,
            "evidence": evidence,
            "latest_research": latest_research,
            "score_history": score_history,
            "previous_plans": previous_plans,
            "allowed_evidence_ids": [
                str(item["id"]) for item in evidence if item.get("id")
            ],
        }
        if user_context is not None:
            input_data["user_context"] = user_context
        return await self.execute(input_data)

    def validate_output(
        self, output: ImprovementPlanOutput, input_data: dict[str, Any]
    ) -> None:
        breakdown = {
            ScoreCriterion(item["criterion"]): int(item["rating"])
            for item in input_data["latest_score"]["breakdown"]
        }
        weakness_criteria = [item.criterion for item in output.weaknesses]
        if len(weakness_criteria) != len(set(weakness_criteria)):
            raise ValueError("Each weak criterion may be diagnosed only once")
        for weakness in output.weaknesses:
            expected = breakdown.get(weakness.criterion)
            if expected is None or weakness.current_rating != expected:
                raise ValueError(
                    f"Rating for {weakness.criterion.value} must match the Judge"
                )
        allowed_evidence = set(input_data["allowed_evidence_ids"])
        cited_evidence = {
            evidence_id
            for weakness in output.weaknesses
            for evidence_id in weakness.evidence_ids
        }
        unknown = cited_evidence - allowed_evidence
        if unknown:
            raise ValueError("Unknown evidence IDs: " + ", ".join(sorted(unknown)))
        diagnosed = set(weakness_criteria)
        if not any(
            diagnosed.intersection(proposal.target_criteria)
            for proposal in output.proposals
        ):
            raise ValueError("At least one proposal must target a diagnosed weakness")
