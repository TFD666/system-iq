"""
Tests for the decision pipeline:
  - questions.py: build_state, build_questions conditional logic
  - policy.py: apply_policy status thresholds, based_on_unknowns flag
  - main.py: POST /design with FakeDecisionProvider, error mappings, logs
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.decision.policy import (
    CHOICE_ACCEPT_P,
    CHOICE_MARGIN,
    CHOICE_TENTATIVE_P,
    NOUL_NO_P,
    NOUL_YES_P,
    apply_policy,
)
from app.decision.provider import (
    Alternative,
    Decision,
    DecisionFormatError,
    DecisionRateLimitError,
    DecisionResultSet,
    DecisionUnavailableError,
    FakeDecisionProvider,
    Question,
)
from app.decision.questions import build_questions, build_state
from app.main import app, get_decision_provider, get_provider
from app.schemas import ExpectedScale, Requirements


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_requirements(**overrides) -> Requirements:
    """Build a minimal Requirements object; override any field as needed."""
    base = dict(
        project_summary="A test app",
        app_type="web",
        core_features=["feature A"],
        user_roles=["user"],
        expected_scale=ExpectedScale(users="1000", peak_requests_per_second=None, data_volume=None),
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


def _question_ids(req: Requirements) -> list[str]:
    """Return the ids of all questions built for req."""
    return [q.id for q in build_questions(req)]


def _choice_decision(
    qid: str,
    top_option: str,
    top_p: float,
    second_option: str = "other",
    second_p: float | None = None,
) -> Decision:
    """Build a minimal choice Decision for policy tests."""
    if second_p is None:
        second_p = 1.0 - top_p
    return Decision(
        id=qid,
        kind="choice",
        choice=top_option,
        probability=top_p,
        alternatives=[
            Alternative(option=top_option, probability=top_p),
            Alternative(option=second_option, probability=second_p),
        ],
        confidence=None,
    )


def _noul_decision(qid: str, p: float) -> Decision:
    """Build a minimal noul Decision for policy tests."""
    return Decision(
        id=qid,
        kind="noul",
        choice=None,
        probability=p,
        alternatives=[],
        confidence=None,
    )


# LLM fake: always returns the same valid JSON so extraction never fails.
_VALID_REQUIREMENTS_JSON = json.dumps({
    "project_summary": "A to-do app",
    "app_type": "web",
    "core_features": ["task creation"],
    "user_roles": ["user"],
    "expected_scale": {"users": "1000", "peak_requests_per_second": None, "data_volume": None},
    "realtime": False,
    "geospatial": False,
    "authentication": True,
    "search_filtering": False,
    "media_storage": False,
    "payments": False,
    "offline_support": False,
    "external_integrations": [],
    "constraints": [],
    "assumptions": [],
    "unknowns": [],
})

from app.llm import LLMProvider, LLMResult


class _GoodLLM(LLMProvider):
    def complete_json(self, system, user, max_tokens) -> LLMResult:
        return LLMResult(text=_VALID_REQUIREMENTS_JSON, prompt_tokens=10, completion_tokens=20)


class _BadLLM(LLMProvider):
    def complete_json(self, system, user, max_tokens) -> LLMResult:
        return LLMResult(text="not json", prompt_tokens=5, completion_tokens=5)


def _make_client(
    llm: LLMProvider | None = None,
    decision_provider=None,
) -> TestClient:
    """Build a TestClient with both dependencies overridden."""
    app.dependency_overrides[get_provider] = lambda: (llm or _GoodLLM())
    app.dependency_overrides[get_decision_provider] = lambda: (
        decision_provider or FakeDecisionProvider()
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# build_questions: conditional question inclusion
# ---------------------------------------------------------------------------

class TestBuildQuestions:

    def test_always_present_questions_are_included(self):
        req = _make_requirements()
        ids = _question_ids(req)
        for expected in [
            "api_style", "primary_database", "architecture_style",
            "cache_needed", "async_processing_needed", "horizontal_scaling_needed",
        ]:
            assert expected in ids, f"Expected '{expected}' in questions"

    # geospatial
    def test_geospatial_true_adds_postgis_option(self):
        req = _make_requirements(geospatial=True)
        qs = {q.id: q for q in build_questions(req)}
        assert "PostgreSQL + PostGIS" in qs["primary_database"].options

    def test_geospatial_false_excludes_postgis_option(self):
        req = _make_requirements(geospatial=False)
        qs = {q.id: q for q in build_questions(req)}
        assert "PostgreSQL + PostGIS" not in qs["primary_database"].options

    def test_geospatial_none_excludes_postgis_option(self):
        req = _make_requirements(geospatial=None)
        qs = {q.id: q for q in build_questions(req)}
        assert "PostgreSQL + PostGIS" not in qs["primary_database"].options

    # authentication
    def test_authentication_true_includes_auth_approach(self):
        req = _make_requirements(authentication=True)
        assert "auth_approach" in _question_ids(req)

    def test_authentication_none_includes_auth_approach(self):
        # None means "not addressed" – we still ask
        req = _make_requirements(authentication=None)
        assert "auth_approach" in _question_ids(req)

    def test_authentication_false_drops_auth_approach(self):
        # Explicitly false → no auth needed, no question
        req = _make_requirements(authentication=False)
        assert "auth_approach" not in _question_ids(req)

    # realtime
    def test_realtime_true_includes_realtime_transport(self):
        req = _make_requirements(realtime=True)
        assert "realtime_transport" in _question_ids(req)

    def test_realtime_false_excludes_realtime_transport(self):
        req = _make_requirements(realtime=False)
        assert "realtime_transport" not in _question_ids(req)

    def test_realtime_none_excludes_realtime_transport(self):
        req = _make_requirements(realtime=None)
        assert "realtime_transport" not in _question_ids(req)

    # media_storage
    def test_media_storage_true_includes_media_storage_approach(self):
        req = _make_requirements(media_storage=True)
        assert "media_storage_approach" in _question_ids(req)

    def test_media_storage_false_excludes_media_storage_approach(self):
        req = _make_requirements(media_storage=False)
        assert "media_storage_approach" not in _question_ids(req)

    def test_media_storage_none_excludes_media_storage_approach(self):
        req = _make_requirements(media_storage=None)
        assert "media_storage_approach" not in _question_ids(req)

    # depends_on
    def test_api_style_depends_on_correct_fields(self):
        req = _make_requirements()
        qs = {q.id: q for q in build_questions(req)}
        assert set(qs["api_style"].depends_on) == {"core_features", "app_type"}

    def test_primary_database_depends_on_correct_fields(self):
        req = _make_requirements()
        qs = {q.id: q for q in build_questions(req)}
        assert set(qs["primary_database"].depends_on) == {"geospatial", "expected_scale"}


# ---------------------------------------------------------------------------
# build_state: structure and privacy
# ---------------------------------------------------------------------------

class TestBuildState:

    def test_state_contains_project_summary(self):
        req = _make_requirements(project_summary="My unique app")
        state = build_state(req)
        assert state["project_summary"] == "My unique app"

    def test_state_does_not_have_idea_field(self):
        # The raw idea string must never be in state
        req = _make_requirements()
        state = build_state(req)
        assert "idea" not in state

    def test_state_has_expected_scale_as_dict(self):
        req = _make_requirements()
        state = build_state(req)
        assert isinstance(state["expected_scale"], dict)


# ---------------------------------------------------------------------------
# apply_policy: choice status thresholds
# ---------------------------------------------------------------------------

class TestChoicePolicy:

    def _q(self) -> Question:
        return Question(id="api_style", kind="choice", text="Pick one.", options=["a", "b", "c"])

    def _req(self) -> Requirements:
        return _make_requirements()

    def test_accepted_when_top_ge_accept_p_and_margin_ge_threshold(self):
        # top = ACCEPT_P, second = top - MARGIN → exactly at the boundary
        top_p = CHOICE_ACCEPT_P          # 0.75
        second_p = top_p - CHOICE_MARGIN # 0.60
        d = _choice_decision("api_style", "REST", top_p, "GraphQL", second_p)
        result = apply_policy(self._q(), d, self._req())
        assert result.status == "accepted"

    def test_tentative_when_top_ge_tentative_but_margin_too_small(self):
        # top = ACCEPT_P but second very close → margin < CHOICE_MARGIN
        top_p = CHOICE_ACCEPT_P          # 0.75
        second_p = top_p - 0.01          # margin = 0.01 < 0.15
        d = _choice_decision("api_style", "REST", top_p, "GraphQL", second_p)
        result = apply_policy(self._q(), d, self._req())
        assert result.status == "tentative"

    def test_tentative_when_top_equals_tentative_p_exactly(self):
        top_p = CHOICE_TENTATIVE_P       # 0.50
        second_p = 0.30
        d = _choice_decision("api_style", "REST", top_p, "GraphQL", second_p)
        result = apply_policy(self._q(), d, self._req())
        assert result.status == "tentative"

    def test_needs_review_when_top_below_tentative_p(self):
        top_p = CHOICE_TENTATIVE_P - 0.01  # just below 0.50
        second_p = 0.30
        d = _choice_decision("api_style", "REST", top_p, "GraphQL", second_p)
        result = apply_policy(self._q(), d, self._req())
        assert result.status == "needs_review"

    def test_choice_field_matches_selected_option(self):
        d = _choice_decision("api_style", "GraphQL", 0.80, "REST", 0.20)
        result = apply_policy(self._q(), d, self._req())
        assert result.choice == "GraphQL"

    def test_top_two_alternatives_present(self):
        d = _choice_decision("api_style", "REST", 0.80, "GraphQL", 0.15)
        result = apply_policy(self._q(), d, self._req())
        assert len(result.top_alternatives) == 2


# ---------------------------------------------------------------------------
# apply_policy: noul status thresholds
# ---------------------------------------------------------------------------

class TestNoulPolicy:

    def _q(self) -> Question:
        return Question(id="cache_needed", kind="noul", text="Need cache?")

    def _req(self) -> Requirements:
        return _make_requirements()

    def test_yes_when_p_equals_yes_threshold(self):
        d = _noul_decision("cache_needed", NOUL_YES_P)  # exactly 0.75
        assert apply_policy(self._q(), d, self._req()).status == "yes"

    def test_yes_when_p_above_yes_threshold(self):
        d = _noul_decision("cache_needed", 0.99)
        assert apply_policy(self._q(), d, self._req()).status == "yes"

    def test_no_when_p_equals_no_threshold(self):
        d = _noul_decision("cache_needed", NOUL_NO_P)   # exactly 0.25
        assert apply_policy(self._q(), d, self._req()).status == "no"

    def test_no_when_p_below_no_threshold(self):
        d = _noul_decision("cache_needed", 0.01)
        assert apply_policy(self._q(), d, self._req()).status == "no"

    def test_uncertain_between_thresholds(self):
        d = _noul_decision("cache_needed", 0.50)
        assert apply_policy(self._q(), d, self._req()).status == "uncertain"

    def test_noul_choice_is_none(self):
        d = _noul_decision("cache_needed", 0.90)
        assert apply_policy(self._q(), d, self._req()).choice is None


# ---------------------------------------------------------------------------
# apply_policy: based_on_unknowns flag
# ---------------------------------------------------------------------------

class TestBasedOnUnknowns:

    def test_false_when_all_depends_on_fields_are_known(self):
        req = _make_requirements(geospatial=True, expected_scale=ExpectedScale(users="1000"))
        q = Question(id="primary_database", kind="choice", text="DB?",
                     options=["PostgreSQL"], depends_on=["geospatial", "expected_scale"])
        d = _choice_decision("primary_database", "PostgreSQL", 0.90)
        result = apply_policy(q, d, req)
        assert result.based_on_unknowns is False

    def test_true_when_depends_on_field_is_none(self):
        # geospatial is None
        req = _make_requirements(geospatial=None)
        q = Question(id="primary_database", kind="choice", text="DB?",
                     options=["PostgreSQL"], depends_on=["geospatial"])
        d = _choice_decision("primary_database", "PostgreSQL", 0.90)
        result = apply_policy(q, d, req)
        assert result.based_on_unknowns is True

    def test_true_when_expected_scale_all_none(self):
        req = _make_requirements(
            expected_scale=ExpectedScale(users=None, peak_requests_per_second=None, data_volume=None)
        )
        q = Question(id="cache_needed", kind="noul", text="Cache?",
                     depends_on=["expected_scale"])
        d = _noul_decision("cache_needed", 0.80)
        result = apply_policy(q, d, req)
        assert result.based_on_unknowns is True

    def test_false_when_expected_scale_partially_known(self):
        # At least one scale field is set → scale is NOT unknown
        req = _make_requirements(
            expected_scale=ExpectedScale(users="500", peak_requests_per_second=None, data_volume=None)
        )
        q = Question(id="cache_needed", kind="noul", text="Cache?",
                     depends_on=["expected_scale"])
        d = _noul_decision("cache_needed", 0.80)
        result = apply_policy(q, d, req)
        assert result.based_on_unknowns is False


# ---------------------------------------------------------------------------
# POST /design with FakeDecisionProvider
# ---------------------------------------------------------------------------

class TestDesignEndpoint:

    def test_returns_200_with_decided_stage(self):
        client = _make_client()
        resp = client.post("/design", json={"idea": "Build a chat app"})
        assert resp.status_code == 200
        assert resp.json()["stage"] == "decided"

    def test_decisions_list_is_present(self):
        client = _make_client()
        resp = client.post("/design", json={"idea": "Build a chat app"})
        body = resp.json()
        assert "decisions" in body
        assert isinstance(body["decisions"], list)
        assert len(body["decisions"]) > 0

    def test_each_decision_has_required_fields(self):
        client = _make_client()
        body = client.post("/design", json={"idea": "Build a chat app"}).json()
        for dec in body["decisions"]:
            assert "id" in dec
            assert "question" in dec
            assert "status" in dec
            assert "probability" in dec
            assert "based_on_unknowns" in dec

    def test_every_decision_has_non_empty_question(self):
        # Each decision must carry a non-empty fixed template sentence.
        client = _make_client()
        body = client.post("/design", json={"idea": "Build a chat app"}).json()
        for dec in body["decisions"]:
            assert dec["question"], f"Decision '{dec['id']}' has an empty question"

    def test_fake_mode_meta_model_label(self):
        # When FakeDecisionProvider is used, meta.decision_model must be the fake label.
        client = _make_client(decision_provider=FakeDecisionProvider(model="fake (demo only)"))
        body = client.post("/design", json={"idea": "Build a chat app"}).json()
        assert body["meta"]["decision_model"] == "fake (demo only)"

    def test_meta_has_token_counts(self):
        client = _make_client()
        body = client.post("/design", json={"idea": "Build a chat app"}).json()
        meta = body["meta"]
        assert "input_tokens" in meta
        assert "output_tokens" in meta

    def test_requirements_still_present(self):
        client = _make_client()
        body = client.post("/design", json={"idea": "Build a chat app"}).json()
        assert "requirements" in body


# ---------------------------------------------------------------------------
# POST /design: decision error mappings
# ---------------------------------------------------------------------------

class _RaisingDecisionProvider(FakeDecisionProvider):
    """A fake decision provider that raises a given exception."""
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    def decide(self, state, questions):
        raise self._exc


class TestDecisionErrorMappings:

    def _client_raising(self, exc: Exception) -> TestClient:
        return _make_client(decision_provider=_RaisingDecisionProvider(exc))

    def test_rate_limit_free_quota_returns_429_with_jev_message(self):
        exc = DecisionRateLimitError(retry_after_seconds=43407, free_quota_exhausted=True)
        resp = self._client_raising(exc).post("/design", json={"idea": "test"})
        assert resp.status_code == 429
        assert "05:30 IST" in resp.json()["detail"]   # IST message for free quota

    def test_rate_limit_generic_returns_429_with_retry_message(self):
        exc = DecisionRateLimitError(retry_after_seconds=30, free_quota_exhausted=False)
        resp = self._client_raising(exc).post("/design", json={"idea": "test"})
        assert resp.status_code == 429
        # Generic message, not the IST one
        assert "rate limit" in resp.json()["detail"].lower()
        assert "05:30 IST" not in resp.json()["detail"]

    def test_unavailable_returns_504(self):
        exc = DecisionUnavailableError("down")
        resp = self._client_raising(exc).post("/design", json={"idea": "test"})
        assert resp.status_code == 504

    def test_format_error_returns_502(self):
        exc = DecisionFormatError("bad shape")
        resp = self._client_raising(exc).post("/design", json={"idea": "test"})
        assert resp.status_code == 502

    def test_error_detail_never_contains_provider_body(self):
        # "bad shape" is internal detail; must not reach the client
        exc = DecisionFormatError("bad shape internal detail")
        resp = self._client_raising(exc).post("/design", json={"idea": "test"})
        assert "bad shape" not in resp.json()["detail"]

    def test_extraction_failure_still_returns_502(self):
        # When LLM fails, we never reach the decision provider
        client = _make_client(llm=_BadLLM())
        resp = client.post("/design", json={"idea": "test"})
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# caplog: no secrets in logs
# ---------------------------------------------------------------------------

class TestNoSecretsInLogs:

    SENSITIVE_IDEA = "my absolutely secret idea xyz987"

    def test_idea_text_not_in_logs_on_success(self, caplog: pytest.LogCaptureFixture):
        client = _make_client()
        with caplog.at_level(logging.DEBUG):
            client.post("/design", json={"idea": self.SENSITIVE_IDEA})
        assert self.SENSITIVE_IDEA not in caplog.text

    def test_idea_text_not_in_logs_on_llm_failure(self, caplog: pytest.LogCaptureFixture):
        client = _make_client(llm=_BadLLM())
        with caplog.at_level(logging.DEBUG):
            client.post("/design", json={"idea": self.SENSITIVE_IDEA})
        assert self.SENSITIVE_IDEA not in caplog.text

    def test_idea_text_not_in_logs_on_decision_error(self, caplog: pytest.LogCaptureFixture):
        exc = DecisionUnavailableError("down")
        client = _make_client(decision_provider=_RaisingDecisionProvider(exc))
        with caplog.at_level(logging.DEBUG):
            client.post("/design", json={"idea": self.SENSITIVE_IDEA})
        assert self.SENSITIVE_IDEA not in caplog.text

    def test_question_text_not_in_logs(self, caplog: pytest.LogCaptureFixture):
        # Question texts are built from fixed templates, but should not appear in logs
        exc = DecisionFormatError("err")
        client = _make_client(decision_provider=_RaisingDecisionProvider(exc))
        with caplog.at_level(logging.DEBUG):
            client.post("/design", json={"idea": self.SENSITIVE_IDEA})
        # Check a fragment unique to a question template
        assert "API communication style" not in caplog.text
