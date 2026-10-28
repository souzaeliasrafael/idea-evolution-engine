from types import MappingProxyType

from app.domain.enums import ScoreCriterion
from app.schemas.judgment import (
    CriterionAssessment,
    ScoreBreakdownItem,
    ScoreCalculation,
)


CRITERION_WEIGHTS = MappingProxyType(
    {
        ScoreCriterion.REAL_PROBLEM: 15,
        ScoreCriterion.PROBLEM_INTENSITY: 10,
        ScoreCriterion.IDENTIFIABLE_USERS: 5,
        ScoreCriterion.MARKET: 10,
        ScoreCriterion.DIFFERENTIATION: 10,
        ScoreCriterion.TECHNICAL_FEASIBILITY: 15,
        ScoreCriterion.ECONOMIC_FEASIBILITY: 10,
        ScoreCriterion.DISTRIBUTION: 5,
        ScoreCriterion.DEFENSIBILITY: 5,
        ScoreCriterion.LEGAL_REGULATORY_RISK: 5,
        ScoreCriterion.TESTABLE_MVP: 5,
        ScoreCriterion.SCALABILITY: 5,
    }
)


class InvalidScoreInputError(ValueError):
    pass


class ScoreEngine:
    @staticmethod
    def calculate(criteria: list[CriterionAssessment]) -> ScoreCalculation:
        by_criterion = {item.criterion: item for item in criteria}
        if len(by_criterion) != len(criteria):
            raise InvalidScoreInputError("Each score criterion must appear exactly once")

        missing = set(CRITERION_WEIGHTS) - set(by_criterion)
        unexpected = set(by_criterion) - set(CRITERION_WEIGHTS)
        if missing or unexpected:
            missing_names = ", ".join(sorted(item.value for item in missing)) or "none"
            unexpected_names = (
                ", ".join(sorted(item.value for item in unexpected)) or "none"
            )
            raise InvalidScoreInputError(
                f"Invalid score criteria; missing={missing_names}; "
                f"unexpected={unexpected_names}"
            )

        breakdown: list[ScoreBreakdownItem] = []
        for criterion, weight in CRITERION_WEIGHTS.items():
            assessment = by_criterion[criterion]
            breakdown.append(
                ScoreBreakdownItem(
                    criterion=criterion,
                    rating=assessment.rating,
                    weight=weight,
                    weighted_score=assessment.rating * weight // 5,
                    rationale=assessment.rationale,
                    evidence_ids=assessment.evidence_ids,
                )
            )

        return ScoreCalculation(
            total_score=sum(item.weighted_score for item in breakdown),
            breakdown=breakdown,
        )

