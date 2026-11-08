"""Tests for app/validation/policy.py -- pure threshold math, no network."""

import pytest

from app.decision.provider import Decision
from app.validation.policy import apply_validation_policy
from app.validation.questions import ValidationQuestion


def _question(polarity: str, sections=None) -> ValidationQuestion:
    return ValidationQuestion(id="val_x", text="Is it?", polarity=polarity, sections=sections or [])


def _decision(p: float) -> Decision:
    return Decision(id="val_x", kind="noul", probability=p)


@pytest.mark.parametrize("p,expected", [
    (0.0, "ok"),
    (0.39, "ok"),
    (0.4, "possible"),   # exact lower boundary of "possible"
    (0.59, "possible"),
    (0.6, "flagged"),    # exact boundary where it becomes "flagged"
    (1.0, "flagged"),
])
def test_problem_polarity_boundaries(p, expected):
    result = apply_validation_policy(_question("problem"), _decision(p))
    assert result.status == expected
    assert result.probability == p


@pytest.mark.parametrize("p,expected", [
    (1.0, "ok"),
    (0.61, "ok"),
    (0.6, "possible"),   # exact upper boundary of "possible"
    (0.41, "possible"),
    (0.4, "flagged"),    # exact boundary where it becomes "flagged"
    (0.0, "flagged"),
])
def test_satisfied_polarity_boundaries(p, expected):
    result = apply_validation_policy(_question("satisfied"), _decision(p))
    assert result.status == expected
    assert result.probability == p


def test_result_carries_question_id_text_and_sections():
    question = ValidationQuestion(id="val_auth", text="Does it?", polarity="satisfied", sections=[6])
    result = apply_validation_policy(question, _decision(0.9))
    assert result.id == "val_auth"
    assert result.text == "Does it?"
    assert result.sections == [6]
