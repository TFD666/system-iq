"""
Policy thresholds for validation answers (plain Jev noul Decisions,
reused from the decision package).

A validation question's "probability" means different things depending
on its polarity:
- "problem" questions: HIGH probability means the problem is likely real.
- "satisfied" questions: LOW probability means it's likely NOT satisfied.
Both read the same 0..1 number; apply_validation_policy just flips which
end of the scale counts as bad, based on question.polarity.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..decision.provider import Decision
from .questions import ValidationQuestion

VAL_PROBLEM_FLAG_P = 0.6
VAL_SATISFIED_FLAG_P = 0.4
VAL_POSSIBLE_BAND = 0.2


@dataclass
class ValidationResult:
    id: str
    text: str
    probability: float
    status: str  # "ok" | "possible" | "flagged"
    sections: list[int]


def apply_validation_policy(question: ValidationQuestion, decision: Decision) -> ValidationResult:
    """
    Problem:   p >= 0.6 -> flagged; p >= 0.4 -> possible; else ok.
    Satisfied: p <= 0.4 -> flagged; p <= 0.6 -> possible; else ok.
    """
    p = decision.probability

    if question.polarity == "problem":
        if p >= VAL_PROBLEM_FLAG_P:
            status = "flagged"
        elif p >= VAL_PROBLEM_FLAG_P - VAL_POSSIBLE_BAND:
            status = "possible"
        else:
            status = "ok"
    else:  # "satisfied"
        if p <= VAL_SATISFIED_FLAG_P:
            status = "flagged"
        elif p <= VAL_SATISFIED_FLAG_P + VAL_POSSIBLE_BAND:
            status = "possible"
        else:
            status = "ok"

    return ValidationResult(
        id=question.id,
        text=question.text,
        probability=p,
        status=status,
        sections=question.sections,
    )
