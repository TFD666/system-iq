"""
Policy layer: turn a raw Decision into a DecisionResult with a human-readable
status and a flag indicating whether the answer is based on unknown inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas import Requirements
from .provider import Alternative, Decision, Question

# ---------------------------------------------------------------------------
# Named thresholds – change these constants to tune the policy globally.
# ---------------------------------------------------------------------------

CHOICE_ACCEPT_P = 0.75      # top option probability needed for "accepted"
CHOICE_MARGIN = 0.15        # gap between top and second needed for "accepted"
CHOICE_TENTATIVE_P = 0.50   # top option probability needed for "tentative"
NOUL_YES_P = 0.75           # noul probability at or above which we say "yes"
NOUL_NO_P = 0.25            # noul probability at or below which we say "no"


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class DecisionResult:
    """
    Human-readable result for one question after policy is applied.
    This is what goes into the API response, not the raw Decision.
    """
    id: str
    question: str               # fixed template sentence for this question id
    status: str                 # "accepted" | "tentative" | "needs_review" | "yes" | "no" | "uncertain"
    choice: str | None          # the selected option (None for noul)
    probability: float          # top probability (yes-probability for noul)
    top_alternatives: list[Alternative]   # top 2 alternatives by probability
    based_on_unknowns: bool     # True if any depends_on field was None/unknown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scale_is_unknown(req: Requirements) -> bool:
    """Return True when ALL three scale fields are None (i.e. scale unknown)."""
    s = req.expected_scale
    return s.users is None and s.peak_requests_per_second is None and s.data_volume is None


def _based_on_unknowns(question: Question, req: Requirements) -> bool:
    """
    Return True if any field listed in depends_on is None (unknown).
    expected_scale is treated as None when all three sub-fields are None.
    """
    for field_name in question.depends_on:
        if field_name == "expected_scale":
            if _scale_is_unknown(req):
                return True
        else:
            value = getattr(req, field_name, None)
            if value is None:
                return True
    return False


def _top_two(alternatives: list[Alternative]) -> list[Alternative]:
    """Return the two highest-probability alternatives, sorted descending."""
    sorted_alts = sorted(alternatives, key=lambda a: a.probability, reverse=True)
    return sorted_alts[:2]


# ---------------------------------------------------------------------------
# Main policy function
# ---------------------------------------------------------------------------

def apply_policy(
    question: Question,
    decision: Decision,
    req: Requirements,
) -> DecisionResult:
    """
    Apply status thresholds to a raw Decision and return a DecisionResult.

    Choice status:
        top >= ACCEPT_P and (top - second) >= MARGIN  →  accepted
        top >= TENTATIVE_P                             →  tentative
        otherwise                                      →  needs_review

    Noul status:
        p >= YES_P   →  yes
        p <= NO_P    →  no
        otherwise    →  uncertain
    """
    unknown_flag = _based_on_unknowns(question, req)
    top2 = _top_two(decision.alternatives)

    if decision.kind == "noul":
        p = decision.probability
        if p >= NOUL_YES_P:
            status = "yes"
        elif p <= NOUL_NO_P:
            status = "no"
        else:
            status = "uncertain"

        return DecisionResult(
            id=decision.id,
            question=question.text,
            status=status,
            choice=None,
            probability=p,
            top_alternatives=top2,
            based_on_unknowns=unknown_flag,
        )

    # choice (score questions are not used, per task rules)
    top_p = top2[0].probability if top2 else 0.0
    second_p = top2[1].probability if len(top2) > 1 else 0.0

    if top_p >= CHOICE_ACCEPT_P and (top_p - second_p) >= CHOICE_MARGIN:
        status = "accepted"
    elif top_p >= CHOICE_TENTATIVE_P:
        status = "tentative"
    else:
        status = "needs_review"

    return DecisionResult(
        id=decision.id,
        question=question.text,
        status=status,
        choice=decision.choice,
        probability=top_p,
        top_alternatives=top2,
        based_on_unknowns=unknown_flag,
    )
