"""Tests for app/design/checks.py. No network involved -- pure text checks."""

from app.design.checks import check_design
from app.design.sections import all_headings
from app.schemas import AlternativeOut, DecisionResultOut

GOOD_MARKDOWN = "\n\n".join(all_headings()) + "\n\nSome body text with no code fences."


def _decision(**overrides) -> DecisionResultOut:
    base = dict(
        id="primary_database",
        question="Which database fits best?",
        status="accepted",
        choice="PostgreSQL",
        probability=0.9,
        top_alternatives=[AlternativeOut(option="PostgreSQL", probability=0.9)],
        based_on_unknowns=False,
    )
    base.update(overrides)
    return DecisionResultOut(**base)


def test_complete_markdown_with_no_decisions_has_no_warnings():
    assert check_design(GOOD_MARKDOWN, decisions=None) == []


def test_missing_heading_is_flagged():
    markdown = GOOD_MARKDOWN.replace("## 7. Caching", "")
    warnings = check_design(markdown, decisions=None)
    assert any("## 7. Caching" in w for w in warnings)


def test_missing_accepted_choice_is_flagged():
    decision = _decision(status="accepted", choice="PostgreSQL")
    # The chosen database name never appears in the body text.
    warnings = check_design(GOOD_MARKDOWN, decisions=[decision])
    assert any(decision.id in w for w in warnings)


def test_accepted_choice_present_case_insensitively_is_not_flagged():
    decision = _decision(status="accepted", choice="PostgreSQL")
    markdown = GOOD_MARKDOWN + "\n\nWe chose postgresql for storage."
    warnings = check_design(markdown, decisions=[decision])
    assert warnings == []


def test_tentative_choice_missing_from_text_is_not_flagged():
    # Only "accepted" choices are required to appear in the text.
    decision = _decision(status="tentative", choice="MongoDB")
    warnings = check_design(GOOD_MARKDOWN, decisions=[decision])
    assert warnings == []


def test_python_code_fence_is_flagged():
    markdown = GOOD_MARKDOWN + "\n\n```python\nprint('hello')\n```\n"
    warnings = check_design(markdown, decisions=None)
    assert any("python" in w for w in warnings)


def test_mermaid_and_text_fences_are_allowed():
    markdown = GOOD_MARKDOWN + "\n\n```mermaid\ngraph TD; A-->B;\n```\n```text\nplain\n```\n"
    warnings = check_design(markdown, decisions=None)
    assert warnings == []


def test_warnings_contain_only_ids_and_headings_no_prose():
    decision = _decision(status="accepted", choice="PostgreSQL")
    markdown = "## 1. Architecture overview\n\nSome prose the LLM wrote."
    warnings = check_design(markdown, decisions=[decision])
    for warning in warnings:
        assert "Some prose the LLM wrote" not in warning
