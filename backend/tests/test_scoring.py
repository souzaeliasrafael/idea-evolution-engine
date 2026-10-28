import pytest

from app.domain.enums import ScoreCriterion
from app.schemas.judgment import CriterionAssessment
from app.scoring.engine import (
    CRITERION_WEIGHTS,
    InvalidScoreInputError,
    ScoreEngine,
)


def assessments(rating: int) -> list[CriterionAssessment]:
    return [
        CriterionAssessment(
            criterion=criterion,
            rating=rating,
            rationale=f"Rating {rating} for {criterion.value}",
            evidence_ids=[],
        )
        for criterion in ScoreCriterion
    ]


def test_weights_total_exactly_100() -> None:
    assert sum(CRITERION_WEIGHTS.values()) == 100
    assert set(CRITERION_WEIGHTS) == set(ScoreCriterion)


@pytest.mark.parametrize(("rating", "expected"), [(0, 0), (3, 60), (4, 80), (5, 100)])
def test_score_engine_calculates_weighted_total(rating: int, expected: int) -> None:
    result = ScoreEngine.calculate(assessments(rating))

    assert result.total_score == expected
    assert len(result.breakdown) == 12
    assert sum(item.weighted_score for item in result.breakdown) == expected


def test_score_engine_rejects_missing_or_duplicate_criteria() -> None:
    missing = assessments(3)[:-1]
    duplicate = assessments(3)
    duplicate[-1] = duplicate[0]

    with pytest.raises(InvalidScoreInputError, match="missing"):
        ScoreEngine.calculate(missing)
    with pytest.raises(InvalidScoreInputError, match="exactly once"):
        ScoreEngine.calculate(duplicate)

