"""
Tests for app/validation/questions.py: which templates appear under
which conditions, and the state builder's safety limits.
"""

import pytest

from app.schemas import AlternativeOut, DecisionResultOut, ExpectedScale, Requirements
from app.validation.questions import (
    MAX_STATE_CHARS,
    ValidationStateTooLargeError,
    build_validation_questions,
    build_validation_state,
)


def _make_requirements(**overrides) -> Requirements:
    base = dict(
        project_summary="A to-do app for small teams.",
        app_type="web",
        core_features=["task creation"],
        user_roles=["user"],
        expected_scale=ExpectedScale(users=None, peak_requests_per_second=None, data_volume=None),
        realtime=False,
        geospatial=False,
        authentication=True,
        search_filtering=False,
        media_storage=False,
        payments=False,
        offline_support=False,
        external_integrations=[],
        constraints=[],
        assumptions=[],
        unknowns=[],
    )
    base.update(overrides)
    return Requirements(**base)


def _make_decision(**overrides) -> DecisionResultOut:
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


def _ids(questions) -> set[str]:
    return {q.id for q in questions}


# ── conditional "satisfied" templates ───────────────────────────────────────

def test_val_geospatial_only_when_geospatial_true():
    assert "val_geospatial" in _ids(build_validation_questions(_make_requirements(geospatial=True), None))
    assert "val_geospatial" not in _ids(build_validation_questions(_make_requirements(geospatial=False), None))
    assert "val_geospatial" not in _ids(build_validation_questions(_make_requirements(geospatial=None), None))


def test_val_search_only_when_search_filtering_true():
    assert "val_search" in _ids(build_validation_questions(_make_requirements(search_filtering=True), None))
    assert "val_search" not in _ids(build_validation_questions(_make_requirements(search_filtering=False), None))


def test_val_auth_only_when_authentication_true():
    assert "val_auth" in _ids(build_validation_questions(_make_requirements(authentication=True), None))
    assert "val_auth" not in _ids(build_validation_questions(_make_requirements(authentication=False), None))


def test_val_decision_only_for_accepted_choice_decisions():
    accepted = _make_decision(id="api_style", status="accepted", choice="REST")
    tentative = _make_decision(id="primary_database", status="tentative", choice="PostgreSQL")
    questions = build_validation_questions(_make_requirements(), [accepted, tentative])
    ids = _ids(questions)
    assert "val_decision_api_style" in ids
    assert "val_decision_primary_database" not in ids  # tentative, not accepted


def test_val_decision_sections_use_the_fixed_map():
    decision = _make_decision(id="auth_approach", status="accepted", choice="JWT")
    questions = build_validation_questions(_make_requirements(), [decision])
    match = next(q for q in questions if q.id == "val_decision_auth_approach")
    assert match.sections == [6]
    assert "JWT" in match.text
    assert "Authentication approach" in match.text


# ── always-present "problem" templates ──────────────────────────────────────

def test_six_problem_questions_are_always_present():
    # Was "five" -- val_incoherent was added as a 6th always-on problem question.
    questions = build_validation_questions(_make_requirements(), None)
    ids = _ids(questions)
    for expected in (
        "val_missing_component", "val_invented", "val_contradiction",
        "val_unneeded_complexity", "val_scale_overclaim", "val_incoherent",
    ):
        assert expected in ids


def test_missing_component_and_invented_question_texts_are_domain_neutral():
    # Was a bar-specific example ("a source of the venue data"/"reviews,
    # ratings or user accounts") that biased validation for other ideas.
    by_id = {q.id: q for q in build_validation_questions(_make_requirements(), None)}
    assert "venue" not in by_id["val_missing_component"].text.lower()
    assert "data source" in by_id["val_missing_component"].text
    assert "extra user roles" in by_id["val_invented"].text


def test_problem_questions_have_their_fixed_sections():
    by_id = {q.id: q for q in build_validation_questions(_make_requirements(), None)}
    assert by_id["val_missing_component"].sections == [2, 8]
    assert by_id["val_invented"].sections == [2, 5]
    assert by_id["val_contradiction"].sections == []
    assert by_id["val_unneeded_complexity"].sections == []
    assert by_id["val_scale_overclaim"].sections == [10]
    assert by_id["val_incoherent"].sections == []


def test_all_questions_are_noul_polarity_is_set():
    questions = build_validation_questions(_make_requirements(geospatial=True), None)
    for q in questions:
        assert q.polarity in ("satisfied", "problem")


# ── build_validation_state ──────────────────────────────────────────────────

DESIGN_MARKDOWN = "## 1. Architecture overview\nSome real design text.\n\n## 13. Assumptions and open questions\n- None."


def test_state_has_no_raw_idea_text_or_project_summary():
    secret_summary = "zzz-raw-idea-marker-zzz"
    requirements = _make_requirements(project_summary=secret_summary)
    state = build_validation_state(requirements, None, DESIGN_MARKDOWN)

    assert secret_summary not in str(state)
    assert "project_summary" not in state["requirements"]


def test_state_includes_section_13():
    state = build_validation_state(_make_requirements(), None, DESIGN_MARKDOWN)
    numbers = {section["number"] for section in state["design"]}
    assert 13 in numbers


def test_state_includes_decision_labels_not_ids():
    decision = _make_decision(id="primary_database", status="accepted", choice="PostgreSQL")
    state = build_validation_state(_make_requirements(), [decision], DESIGN_MARKDOWN)
    assert state["decisions"][0]["label"] == "Primary database"
    assert state["decisions"][0]["choice"] == "PostgreSQL"


def test_state_refuses_when_over_20000_characters():
    huge_markdown = "## 1. Architecture overview\n" + ("word " * 10_000)
    with pytest.raises(ValidationStateTooLargeError):
        build_validation_state(_make_requirements(), None, huge_markdown)


def test_max_state_chars_constant_is_20000():
    assert MAX_STATE_CHARS == 20_000
