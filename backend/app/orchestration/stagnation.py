from collections.abc import Sequence


class StagnationDetector:
    MINIMUM_IMPROVEMENT = 3
    CONSECUTIVE_DELTAS = 3

    @classmethod
    def detect(cls, scores: Sequence[int]) -> bool:
        required_scores = cls.CONSECUTIVE_DELTAS + 1
        if len(scores) < required_scores:
            return False
        recent = scores[-required_scores:]
        improvements = [
            current - previous
            for previous, current in zip(recent, recent[1:])
        ]
        return all(value < cls.MINIMUM_IMPROVEMENT for value in improvements)
