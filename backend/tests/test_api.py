"""
Tests for the FastAPI /design endpoint and GroqProvider 429 handling.

The GroqProvider 429 tests mock httpx.post and time.sleep so no real
network calls or real sleeping occur.
"""
import json
import re
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractionError
from app.llm import (
    GROQ_API_URL,
    MAX_RATE_LIMIT_RETRIES,
    MAX_TRANSIENT_RETRIES,
    GroqAuthError,
    LLMProvider,
    LLMResult,
    LLMUnavailableError,
    GroqProvider,
    RateLimitError,
)
from app.decision.provider import (
    Alternative,
    Decision,
    DecisionAuthError,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionResultSet,
    FakeDecisionProvider,
)
from app.main import app, get_provider, get_decision_provider

# ── shared fixture data ────────────────────────────────────────────────────────

VALID_JSON = json.dumps({
    "project_summary": "A to-do app",
    "app_type": "web",
    "core_features": ["task creation"],
    "user_roles": ["user"],
    "expected_scale": {
        "users": None,
        "peak_requests_per_second": None,
        "data_volume": None,
    },
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


# ── fake providers ─────────────────────────────────────────────────────────────

class AlwaysGoodProvider(LLMProvider):
    """Always returns the valid JSON fixture."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)


class AlwaysFailProvider(LLMProvider):
    """Always raises ExtractionError (simulates total model failure)."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        # Return garbage so extraction.py raises ExtractionError after retries
        return LLMResult(text="not json", prompt_tokens=5, completion_tokens=5)


class RateLimitProvider(LLMProvider):
    """Always raises RateLimitError immediately."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise RateLimitError("Groq rate limit hit and retries exhausted.")


class GroqAuthFailProvider(LLMProvider):
    """Always raises GroqAuthError (simulates a rejected Groq API key)."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise GroqAuthError("Groq rejected the API key (HTTP 401)")


class AuthFailDecisionProvider(DecisionProvider):
    """Always raises DecisionAuthError (simulates a rejected Jev API key)."""
    def decide(self, state, questions) -> DecisionResultSet:
        raise DecisionAuthError("Decision service rejected the API key (HTTP 401)")


class GoodProviderWithDesign(LLMProvider):
    """Succeeds at extraction AND at writing the design (complete_text)."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        # Echo back the real headings with >= 80 words each so the
        # per-group quality gate passes on the first try (no retries) --
        # otherwise every group would retry for having no real headings.
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        filler = " ".join(["Some generated section text."] * 21)  # 4 words x 21 = 84
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)


class DesignRateLimitedProvider(LLMProvider):
    """Succeeds at extraction, but hits a rate limit while writing the design."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise RateLimitError("Groq rate limit hit and retries exhausted.")


class CrashingDesignProvider(LLMProvider):
    """Succeeds at extraction, but raises an unexpected error while writing
    the design -- proves an arbitrary exception becomes a clean 500, not a
    500 with a traceback or an uncaught crash."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        raise RuntimeError("super secret design text that must never leak into a log or response")


# ── TestClient factory ─────────────────────────────────────────────────────────

def make_client(provider: LLMProvider) -> TestClient:
    """
    Override both FastAPI dependencies so no real LLM or Jev API is called.
    The decision provider is always a FakeDecisionProvider in these tests.
    The override is cleared after each test via the autouse fixture.
    """
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_decision_provider] = lambda: FakeDecisionProvider()
    return TestClient(app)


def make_client_with_decision(provider: LLMProvider, decision_provider: DecisionProvider) -> TestClient:
    """Like make_client, but lets the test pick the decision provider too."""
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_decision_provider] = lambda: decision_provider
    return TestClient(app)


def make_client_real_decision(provider: LLMProvider) -> TestClient:
    """
    Override only the LLM provider; get_decision_provider runs for real so a
    JevProvider construction error (missing key, paid-model guard) surfaces.
    """
    app.dependency_overrides[get_provider] = lambda: provider
    return TestClient(app)


def make_client_real_llm(decision_provider: DecisionProvider) -> TestClient:
    """
    Override only the decision provider; get_provider runs for real so a
    GroqProvider construction error (missing key) surfaces.
    """
    app.dependency_overrides[get_decision_provider] = lambda: decision_provider
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    # Ensure overrides do not leak between tests
    yield
    app.dependency_overrides.clear()


# ── /design endpoint tests ─────────────────────────────────────────────────────

def test_valid_idea_returns_200_and_stage_decided():
    # The default stage is now "validate" (the full pipeline), so this test
    # must ask for stage="decide" explicitly to still exercise/assert the
    # "decided" stopping point -- that's the point of this specific test.
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "decide"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "decided"   # was "extracted" before decision wiring
    assert "requirements" in body


def test_empty_idea_returns_422():
    # FastAPI validates DesignRequest before calling our handler
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": ""})
    assert response.status_code == 422


def test_idea_over_20000_chars_returns_422():
    # Pydantic max_length=20000 on DesignRequest.idea
    client = make_client(AlwaysGoodProvider())
    long_idea = "x" * 20_001
    response = client.post("/design", json={"idea": long_idea})
    assert response.status_code == 422


def test_provider_extraction_failure_returns_502():
    # AlwaysFailProvider returns garbage both times → ExtractionError → 502
    client = make_client(AlwaysFailProvider())
    response = client.post("/design", json={"idea": "Build something"})
    assert response.status_code == 502
    assert "extract" in response.json()["detail"].lower()


def test_rate_limit_error_returns_429():
    # RateLimitProvider raises RateLimitError → endpoint returns HTTP 429
    client = make_client(RateLimitProvider())
    response = client.post("/design", json={"idea": "Build something"})
    assert response.status_code == 429
    assert "wait" in response.json()["detail"].lower()


# ── stage switching ──────────────────────────────────────────────────────────

def test_stage_extract_returns_extracted_and_skips_decisions():
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "extract"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "extracted"
    assert body["decisions"] is None
    assert body["meta"] is None
    assert body["design_markdown"] is None


def test_stage_decide_returns_decided_and_skips_design():
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "decide"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "decided"
    assert body["decisions"] is not None
    assert body["meta"] is not None
    assert body["design_markdown"] is None
    assert body["design_warnings"] is None
    # The design-only meta fields must stay unset at this stage.
    assert body["meta"]["llm_model"] is None


def test_stage_design_returns_markdown_and_warnings():
    # Renamed: the default stage is now "validate" (not "design"), so
    # this test -- about the design step specifically -- now asks for
    # stage="design" explicitly instead of relying on the old default.
    client = make_client(GoodProviderWithDesign())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "design"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "designed"
    assert body["design_markdown"]
    assert isinstance(body["design_warnings"], list)

    meta = body["meta"]
    assert meta["llm_model"]
    assert meta["design_prompt_tokens"] == 15 * 4  # 4 section groups
    assert meta["design_completion_tokens"] == 25 * 4


def test_design_stage_rate_limit_returns_429():
    client = make_client(DesignRateLimitedProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "design"})
    assert response.status_code == 429
    assert "wait" in response.json()["detail"].lower()


def test_invalid_stage_returns_422():
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "bogus"})
    assert response.status_code == 422


# ── validate stage ───────────────────────────────────────────────────────────

# "problem" validation ids: a HIGH forced probability means "flagged".
# "satisfied" ones (everything else _ScriptedValidationProvider sees): a
# LOW forced probability means "flagged". Mirrors validation/policy.py.
_PROBLEM_VAL_IDS = {
    "val_missing_component", "val_invented", "val_contradiction",
    "val_unneeded_complexity", "val_scale_overclaim", "val_incoherent",
}


class AlwaysFlagValidationDecisionProvider(DecisionProvider):
    """
    Decide step: a plain accepted choice / "no" noul for every question.
    Validation step: every validation question is forced to "flagged",
    so the pipeline keeps revising until it hits max_revisions.
    """
    def __init__(self) -> None:
        self.decide_calls = 0  # only counts validation calls, not the decide step

    def decide(self, state, questions) -> DecisionResultSet:
        if any(q.id.startswith("val_") for q in questions):
            self.decide_calls += 1
        decisions: dict[str, Decision] = {}
        for q in questions:
            if q.id.startswith("val_"):
                p = 0.9 if q.id in _PROBLEM_VAL_IDS else 0.1
                decisions[q.id] = Decision(id=q.id, kind="noul", probability=p)
            elif q.kind == "choice":
                option = q.options[0] if q.options else "X"
                decisions[q.id] = Decision(
                    id=q.id, kind="choice", choice=option, probability=0.9,
                    alternatives=[Alternative(option=option, probability=0.9)],
                )
            else:
                decisions[q.id] = Decision(id=q.id, kind="noul", probability=0.1)
        return DecisionResultSet(
            decisions=decisions, model="scripted", input_tokens=5, output_tokens=5,
            billing_source="free", cost=0.0,
        )


class RateLimitOnValidationDecisionProvider(DecisionProvider):
    """Succeeds at the decide step, but validation calls hit a rate limit."""

    def decide(self, state, questions) -> DecisionResultSet:
        if any(q.id.startswith("val_") for q in questions):
            raise DecisionRateLimitError(retry_after_seconds=5)
        decisions: dict[str, Decision] = {}
        for q in questions:
            if q.kind == "choice":
                option = q.options[0] if q.options else "X"
                decisions[q.id] = Decision(
                    id=q.id, kind="choice", choice=option, probability=0.9,
                    alternatives=[Alternative(option=option, probability=0.9)],
                )
            else:
                decisions[q.id] = Decision(id=q.id, kind="noul", probability=0.1)
        return DecisionResultSet(
            decisions=decisions, model="scripted", input_tokens=5, output_tokens=5,
            billing_source="free", cost=0.0,
        )


@pytest.mark.parametrize("max_revisions,expected_calls", [(0, 1), (1, 2), (2, 3)])
def test_validate_stage_jev_call_counts_follow_max_revisions(max_revisions, expected_calls):
    provider = AlwaysFlagValidationDecisionProvider()
    client = make_client_with_decision(GoodProviderWithDesign(), provider)
    response = client.post(
        "/design", json={"idea": "Build a to-do app", "max_revisions": max_revisions}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "validated"
    assert provider.decide_calls == expected_calls
    assert body["meta"]["validation_calls"] == expected_calls
    assert body["meta"]["validation_model"] == "scripted"
    assert len(body["revisions"]) == min(max_revisions, expected_calls - 1)


def test_flagged_without_sections_only_warns_never_blocks_other_revisions():
    provider = AlwaysFlagValidationDecisionProvider()
    client = make_client_with_decision(GoodProviderWithDesign(), provider)
    response = client.post("/design", json={"idea": "Build a to-do app", "max_revisions": 1})
    body = response.json()
    # val_contradiction / val_unneeded_complexity have sections=[] -- they
    # can only ever warn, never trigger a revision of their own.
    assert "validation: val_contradiction" in body["design_warnings"]
    assert "validation: val_unneeded_complexity" in body["design_warnings"]


def test_fake_mode_never_revises(monkeypatch):
    monkeypatch.setenv("DECISION_PROVIDER", "fake")
    client = make_client_real_decision(GoodProviderWithDesign())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 200
    body = response.json()
    # FakeDecisionProvider answers everything with probability 0.5, which
    # reads as "possible" on both polarities -- never "flagged".
    assert body["revisions"] == []
    assert body["meta"]["validation_status"] == "passed"
    assert all(r["status"] != "flagged" for r in body["validation"])
    assert body["meta"]["validation_model"] == "fake (demo only)"


def test_validation_rate_limit_still_returns_the_design_as_skipped():
    client = make_client_with_decision(GoodProviderWithDesign(), RateLimitOnValidationDecisionProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "validated"
    assert body["design_markdown"]  # the design itself is still returned
    assert body["meta"]["validation_status"] == "skipped"
    assert body["meta"]["validation_model"] is None  # never got a successful decide() call
    assert any("rate limited" in w for w in body["design_warnings"])


class _ExplodingDecisionProvider(DecisionProvider):
    """Fails the test if .decide() is ever called -- used to prove llm_only
    makes zero decision-provider requests."""
    def decide(self, state, questions) -> DecisionResultSet:
        raise AssertionError("decision provider must not be called in llm_only mode")


def test_llm_only_mode_makes_no_decision_provider_request():
    client = make_client_with_decision(GoodProviderWithDesign(), _ExplodingDecisionProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "mode": "llm_only"})

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "designed"
    assert body["decisions"] is None
    assert body["meta"]["decision_model"] == "none (llm-only baseline)"
    assert body["meta"]["validation_calls"] is None
    assert body["meta"]["validation_status"] is None
    assert body["meta"]["llm_model"]
    assert body["meta"]["design_group_stats"]


def test_llm_only_mode_response_shape_matches_pipeline_designed_stage():
    # Same response shape as a normal "designed" stage response, modulo meta.
    client = make_client(GoodProviderWithDesign())
    pipeline_response = client.post(
        "/design", json={"idea": "Build a to-do app", "stage": "design"}
    )
    llm_only_response = client.post(
        "/design", json={"idea": "Build a to-do app", "mode": "llm_only", "stage": "validate"}
    )
    assert set(pipeline_response.json().keys()) == set(llm_only_response.json().keys())
    # mode=llm_only always stops at "designed" even if stage asked for more.
    assert llm_only_response.json()["stage"] == "designed"


def test_unexpected_error_while_writing_design_becomes_clean_500(caplog):
    import logging
    client = make_client(CrashingDesignProvider())
    with caplog.at_level(logging.ERROR):
        response = client.post("/design", json={"idea": "Build a to-do app", "stage": "design"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal error while writing the design. Try again."
    for record in caplog.records:
        assert "super secret design text" not in record.getMessage()
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)


def test_unexpected_error_while_writing_llm_only_design_becomes_clean_500(caplog):
    import logging
    client = make_client(CrashingDesignProvider())
    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/design", json={"idea": "Build a to-do app", "mode": "llm_only"}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal error while writing the design. Try again."
    for record in caplog.records:
        assert "super secret design text" not in record.getMessage()


class _CrashingValidationDecisionProvider(DecisionProvider):
    """Succeeds at the decide step, but raises an unexpected error on the
    validate stage's decide() call (identified by its val_* question ids)."""
    def decide(self, state, questions) -> DecisionResultSet:
        if any(q.id.startswith("val_") for q in questions):
            raise RuntimeError("super secret design text that must never leak into a log or response")
        decisions: dict[str, Decision] = {}
        for q in questions:
            if q.kind == "choice":
                option = q.options[0] if q.options else "X"
                decisions[q.id] = Decision(id=q.id, kind="choice", choice=option, probability=0.9)
            else:
                decisions[q.id] = Decision(id=q.id, kind="noul", probability=0.1)
        return DecisionResultSet(
            decisions=decisions, model="scripted", input_tokens=5, output_tokens=5,
            billing_source="free", cost=0.0,
        )


def test_unexpected_error_during_validation_becomes_clean_500(caplog):
    import logging
    client = make_client_with_decision(GoodProviderWithDesign(), _CrashingValidationDecisionProvider())
    with caplog.at_level(logging.ERROR):
        response = client.post("/design", json={"idea": "Build a to-do app"})

    assert response.status_code == 500
    # After the pipeline refactor the endpoint has a single catch-all; the
    # message is generic rather than stage-specific.
    assert "Try again" in response.json()["detail"]
    for record in caplog.records:
        assert "super secret design text" not in record.getMessage()
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)


def test_no_validation_text_or_design_text_in_logs(caplog):
    import logging
    provider = AlwaysFlagValidationDecisionProvider()
    client = make_client_with_decision(GoodProviderWithDesign(), provider)
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/design", json={"idea": "Build a to-do app", "max_revisions": 2}
        )
    markdown = response.json()["design_markdown"]
    for record in caplog.records:
        message = record.getMessage()
        assert markdown not in message
        assert "Some generated section text" not in message


class AlwaysBadDesignProvider(LLMProvider):
    """Succeeds at extraction, but complete_text never produces real headings."""
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        return LLMResult(text="nothing useful", prompt_tokens=5, completion_tokens=5)


def test_design_warnings_reach_the_http_response():
    # Verifies the warnings plumbing end to end: a group that's bad even
    # after its retry must show up in the JSON response's design_warnings.
    client = make_client(AlwaysBadDesignProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 200
    body = response.json()
    assert body["design_warnings"]
    assert any("missing heading" in w for w in body["design_warnings"])


def test_design_group_stats_reach_the_http_response():
    client = make_client(GoodProviderWithDesign())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 200
    stats = response.json()["meta"]["design_group_stats"]
    assert len(stats) == 4
    for stat in stats:
        assert stat["id"] in {"g1", "g2", "g3", "g4"}
        assert stat["retries"] == 0
        assert stat["prompt_tokens"] == 15
        assert stat["completion_tokens"] == 25
        assert stat["elapsed_seconds"] >= 0


def test_replay_mode_decision_provider_reports_replay_label(tmp_path, monkeypatch):
    replay_file = tmp_path / "saved.json"
    replay_file.write_text(json.dumps({"decisions": []}), encoding="utf-8")
    monkeypatch.setenv("DECISION_PROVIDER", "replay")
    monkeypatch.setenv("DECISION_REPLAY_FILE", str(replay_file))

    client = make_client_real_decision(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "decide"})

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["decision_model"] == "replay (saved Jev output, not a live call)"
    assert meta["decision_billing"] == "free"
    assert meta["decision_cost"] == 0.0


def test_replay_mode_without_file_env_returns_503(monkeypatch):
    monkeypatch.setenv("DECISION_PROVIDER", "replay")
    monkeypatch.delenv("DECISION_REPLAY_FILE", raising=False)

    client = make_client_real_decision(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "decide"})

    assert response.status_code == 503
    assert "DECISION_REPLAY_FILE" in response.json()["detail"]


# ── auth / misconfiguration error mapping ───────────────────────────────────────
# Reproduces the bug: a rejected Jev API key used to surface as
# DecisionUnavailableError -> HTTP 504, which the CLI prints as "backend
# timed out talking to the model" -- hiding a bad key behind a timeout.

def test_decision_auth_error_returns_502_with_detail():
    client = make_client_with_decision(AlwaysGoodProvider(), AuthFailDecisionProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "OPENCODE_API_KEY" in detail


def test_groq_auth_error_returns_502_with_detail():
    client = make_client(GroqAuthFailProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "GROQ_API_KEY" in detail


def test_missing_decision_api_key_returns_503(monkeypatch):
    # No override for get_decision_provider: JevProvider() construction runs
    # for real and raises ValueError for the missing key, which must become
    # a clean 503, not an unhandled 500 with a stack trace.
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.setenv("DECISION_PROVIDER", "jev")
    client = make_client_real_decision(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "misconfigured" in detail
    assert "OPENCODE_API_KEY" in detail
    assert "Traceback" not in response.text


def test_paid_model_guard_returns_503_with_detail(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("JEV_MODEL", "jev-1.13-pro")  # not "-free"
    monkeypatch.delenv("ALLOW_PAID_JEV", raising=False)
    monkeypatch.setenv("DECISION_PROVIDER", "jev")
    client = make_client_real_decision(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "misconfigured" in detail
    assert "ALLOW_PAID_JEV" in detail
    assert "fake-key-for-tests" not in detail


def test_missing_groq_api_key_returns_503(monkeypatch):
    # No override for get_provider: GroqProvider() construction runs for
    # real and raises EnvironmentError for the missing key.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = make_client_real_llm(FakeDecisionProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "misconfigured" in detail
    assert "GROQ_API_KEY" in detail
    assert "Traceback" not in response.text


# ── GroqProvider 429 / retry tests (mocked httpx + mocked sleep) ───────────────

def _make_429_response(retry_after: int = 1) -> MagicMock:
    """Build a mock httpx.Response that looks like a Groq 429."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.headers = {"retry-after": str(retry_after)}
    return resp


def _make_429_message_response(message: str) -> MagicMock:
    """
    Build a mock 429 Response with NO Retry-After header, so GroqProvider
    is forced to parse the wait time out of the error message text instead.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.headers = {}
    resp.json.return_value = {"error": {"message": message}}
    return resp


def _make_200_response(text: str = VALID_JSON) -> MagicMock:
    """Build a mock httpx.Response that looks like a successful Groq response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.headers = {}
    resp.raise_for_status = MagicMock()  # no-op — 200 should not raise
    resp.json.return_value = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 50},
    }
    return resp


@pytest.fixture
def groq_provider(monkeypatch):
    """A GroqProvider with a fake API key so __init__ does not raise."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")
    return GroqProvider()


def test_429_then_success_retries_and_returns(groq_provider):
    """
    First HTTP call returns 429, second returns 200.
    time.sleep must be called once (the retry wait), and the result must be valid.
    """
    responses = [_make_429_response(retry_after=2), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses) as mock_post, \
         patch("app.llm.time.sleep") as mock_sleep:

        result = groq_provider.complete_json(
            system="sys", user="usr", max_tokens=100
        )

    # The wait is now the requested delay PLUS a 1s buffer (never a shorter
    # guess than what was actually requested), so retry_after=2 -> 3.
    mock_sleep.assert_called_once_with(3)
    # httpx.post was called twice total
    assert mock_post.call_count == 2
    # The successful response's token counts come through
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 50


def test_429_three_times_raises_rate_limit_error(groq_provider):
    """
    MAX_RATE_LIMIT_RETRIES + 1 429s in a row exhaust all retries and must
    raise RateLimitError. sleep is called on every attempt except the last.
    """
    responses = [_make_429_response()] * (MAX_RATE_LIMIT_RETRIES + 1)

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep") as mock_sleep:

        with pytest.raises(RateLimitError):
            groq_provider.complete_json(
                system="sys", user="usr", max_tokens=100
            )

    # sleep is called for attempt 0 and 1 only; attempt 2 raises instead
    assert mock_sleep.call_count == MAX_RATE_LIMIT_RETRIES


# ── 429 wait-time parsing (header vs. message text) ─────────────────────────────
# Reproduces the bug: Groq's free-tier output-token limit asked for ~14.7s
# and we only waited ~4s/8s, because we weren't reading the message at all.

def test_429_wait_time_comes_from_retry_after_header_when_present(groq_provider):
    # retry-after header says 2s; message text (ignored) says something else.
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.headers = {"retry-after": "2"}
    resp.json.return_value = {"error": {"message": "try again in 99s"}}
    responses = [resp, _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep") as mock_sleep:
        groq_provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_called_once_with(3)  # header value (2) + 1s buffer


def test_429_wait_time_parsed_from_decimal_seconds_message(groq_provider):
    message = "Limit 1000, Used 660, Requested 585. Please try again in 14.7s."
    responses = [_make_429_message_response(message), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep") as mock_sleep:
        groq_provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_called_once_with(15.7)  # 14.7 + 1s buffer


def test_429_wait_time_parsed_from_minutes_only_message(groq_provider):
    message = "Please try again in 1m."
    responses = [_make_429_message_response(message), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep") as mock_sleep:
        groq_provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_called_once_with(61)  # 60 + 1s buffer


def test_429_requested_wait_over_cap_raises_immediately_without_sleeping(groq_provider):
    # "2m5.3s" = 125.3s, well over the 65s cap -- must fail fast, not sleep.
    message = "Please try again in 2m5.3s."
    resp = _make_429_message_response(message)

    with patch("app.llm.httpx.post", return_value=resp), \
         patch("app.llm.time.sleep") as mock_sleep:
        with pytest.raises(RateLimitError) as exc_info:
            groq_provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_not_called()
    assert exc_info.value.retry_after_seconds == pytest.approx(125.3)


def test_429_never_logs_the_provider_message_text(groq_provider, caplog):
    # The message text can contain an organisation id; only numbers may be logged.
    message = "org_abc123xyz rate limit hit. Please try again in 2s."
    responses = [_make_429_message_response(message), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep"):
        with caplog.at_level(logging.DEBUG):
            groq_provider.complete_json(system="sys", user="usr", max_tokens=100)

    for record in caplog.records:
        assert "org_abc123xyz" not in record.getMessage()


# ── GroqProvider transient error retry tests (5xx / timeouts) ──────────────────

def _make_status_response(status: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = {}
    return resp


@pytest.fixture
def groq_provider_with_injected_sleep(monkeypatch):
    """A GroqProvider whose transient-retry sleep is a plain mock, injected
    through the constructor (not module-level time.sleep)."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")
    mock_sleep = MagicMock()
    return GroqProvider(sleep=mock_sleep), mock_sleep


def test_503_then_success_retries_and_succeeds(groq_provider_with_injected_sleep):
    provider, mock_sleep = groq_provider_with_injected_sleep
    responses = [_make_status_response(503), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses) as mock_post:
        result = provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_called_once_with(5.0)
    assert mock_post.call_count == 2
    assert result.prompt_tokens == 30


def test_503_three_times_raises_llm_unavailable_error(groq_provider_with_injected_sleep):
    provider, mock_sleep = groq_provider_with_injected_sleep
    responses = [_make_status_response(503)] * (MAX_TRANSIENT_RETRIES + 1)

    with patch("app.llm.httpx.post", side_effect=responses):
        with pytest.raises(LLMUnavailableError):
            provider.complete_json(system="sys", user="usr", max_tokens=100)

    assert mock_sleep.call_args_list == [((5.0,),), ((15.0,),)]


def test_design_endpoint_answers_503_when_llm_unavailable():
    class _UnavailableProvider(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            raise LLMUnavailableError("gone")

    client = make_client(_UnavailableProvider())
    response = client.post("/design", json={"idea": "Build a to-do app", "stage": "extract"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The language model service is temporarily unavailable. Try again in a few minutes."
    )


@pytest.mark.parametrize("exc_cls", [httpx.TimeoutException, httpx.ConnectError])
def test_timeout_and_connection_error_count_as_transient(groq_provider_with_injected_sleep, exc_cls):
    provider, mock_sleep = groq_provider_with_injected_sleep

    with patch("app.llm.httpx.post", side_effect=[exc_cls("boom"), _make_200_response()]):
        result = provider.complete_json(system="sys", user="usr", max_tokens=100)

    mock_sleep.assert_called_once_with(5.0)
    assert result.prompt_tokens == 30


def test_transient_retry_logs_only_status_code_and_attempt_number(groq_provider_with_injected_sleep, caplog):
    import logging
    provider, _mock_sleep = groq_provider_with_injected_sleep
    responses = [_make_status_response(502), _make_200_response()]

    with patch("app.llm.httpx.post", side_effect=responses):
        with caplog.at_level(logging.INFO):
            provider.complete_json(system="sys", user="usr", max_tokens=100)

    transient_records = [r for r in caplog.records if "502" in r.getMessage()]
    assert transient_records
    for record in transient_records:
        message = record.getMessage()
        assert "502" in message
        assert "attempt 2/3" in message


@pytest.mark.parametrize("status", [401, 403])
def test_groq_401_and_403_raise_auth_error(groq_provider, status):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = {}

    with patch("app.llm.httpx.post", return_value=resp):
        with pytest.raises(GroqAuthError, match=str(status)):
            groq_provider.complete_json(system="sys", user="usr", max_tokens=100)


def test_complete_text_returns_result_without_json_mode(groq_provider):
    # complete_text must NOT set response_format (that's JSON-mode only).
    resp = _make_200_response(text="# Some Markdown\n\nBody text.")

    with patch("app.llm.httpx.post", return_value=resp) as mock_post:
        result = groq_provider.complete_text(system="sys", user="usr", max_tokens=100)

    sent_payload = mock_post.call_args.kwargs["json"]
    assert "response_format" not in sent_payload
    assert result.text == "# Some Markdown\n\nBody text."
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 50


def test_complete_text_strips_leftover_think_tags(groq_provider):
    resp = _make_200_response(text="<think>reasoning...</think># Heading\n\nBody.")

    with patch("app.llm.httpx.post", return_value=resp):
        result = groq_provider.complete_text(system="sys", user="usr", max_tokens=100)

    assert "<think>" not in result.text
    assert result.text == "# Heading\n\nBody."


def test_complete_text_uses_groq_design_model_env_var(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("GROQ_MODEL", "extraction-model")
    monkeypatch.setenv("GROQ_DESIGN_MODEL", "design-model")
    provider = GroqProvider()

    with patch("app.llm.httpx.post", return_value=_make_200_response()) as mock_post:
        provider.complete_text(system="sys", user="usr", max_tokens=100)

    assert mock_post.call_args.kwargs["json"]["model"] == "design-model"


def test_complete_json_still_uses_groq_model_env_var(monkeypatch):
    # Extraction keeps using GROQ_MODEL even when GROQ_DESIGN_MODEL is set.
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("GROQ_MODEL", "extraction-model")
    monkeypatch.setenv("GROQ_DESIGN_MODEL", "design-model")
    provider = GroqProvider()

    with patch("app.llm.httpx.post", return_value=_make_200_response()) as mock_post:
        provider.complete_json(system="sys", user="usr", max_tokens=100)

    assert mock_post.call_args.kwargs["json"]["model"] == "extraction-model"


def test_complete_text_falls_back_to_groq_model_without_design_model_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("GROQ_MODEL", "extraction-model")
    monkeypatch.delenv("GROQ_DESIGN_MODEL", raising=False)
    provider = GroqProvider()

    with patch("app.llm.httpx.post", return_value=_make_200_response()) as mock_post:
        provider.complete_text(system="sys", user="usr", max_tokens=100)

    assert mock_post.call_args.kwargs["json"]["model"] == "extraction-model"


@pytest.mark.parametrize("status", [401, 403])
def test_complete_text_401_and_403_raise_auth_error(groq_provider, status):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = {}

    with patch("app.llm.httpx.post", return_value=resp):
        with pytest.raises(GroqAuthError, match=str(status)):
            groq_provider.complete_text(system="sys", user="usr", max_tokens=100)


# ── log-leak tests ─────────────────────────────────────────────────────────────

import logging

SENSITIVE_IDEA = "my secret idea with sk-abcdefghijklmnopqrstuvwxyz1234"


def test_idea_text_does_not_appear_in_logs_on_success(caplog):
    """
    After a successful /design call, the idea text must not appear in any
    log record at any level.
    stage="extract" here: this test only cares about the extraction step's
    logging, and AlwaysGoodProvider doesn't implement complete_text (which
    the default stage="design" would now also call).
    """
    client = make_client(AlwaysGoodProvider())
    with caplog.at_level(logging.DEBUG):
        response = client.post("/design", json={"idea": SENSITIVE_IDEA, "stage": "extract"})
    assert response.status_code == 200

    for record in caplog.records:
        assert SENSITIVE_IDEA not in record.getMessage(), (
            f"Idea text leaked into log record: {record.getMessage()!r}"
        )


def test_idea_text_does_not_appear_in_logs_on_extraction_failure(caplog):
    """
    After an ExtractionError path (502), the idea text must not appear in
    any log record.
    """
    client = make_client(AlwaysFailProvider())
    with caplog.at_level(logging.DEBUG):
        response = client.post("/design", json={"idea": SENSITIVE_IDEA})
    assert response.status_code == 502

    for record in caplog.records:
        assert SENSITIVE_IDEA not in record.getMessage(), (
            f"Idea text leaked into log record: {record.getMessage()!r}"
        )


def test_idea_text_does_not_appear_in_502_error_response():
    """
    The 502 error response body must not echo back the idea text.
    """
    client = make_client(AlwaysFailProvider())
    response = client.post("/design", json={"idea": SENSITIVE_IDEA})
    assert response.status_code == 502
    assert SENSITIVE_IDEA not in response.text


def test_idea_text_does_not_leak_on_decision_auth_error(caplog):
    """
    The 502 from a rejected Jev key must not echo the idea text in the
    response body or in any log record.
    """
    client = make_client_with_decision(AlwaysGoodProvider(), AuthFailDecisionProvider())
    with caplog.at_level(logging.DEBUG):
        response = client.post("/design", json={"idea": SENSITIVE_IDEA})
    assert response.status_code == 502
    assert SENSITIVE_IDEA not in response.text
    for record in caplog.records:
        assert SENSITIVE_IDEA not in record.getMessage()


def test_idea_text_does_not_leak_on_groq_auth_error(caplog):
    """
    The 502 from a rejected Groq key must not echo the idea text in the
    response body or in any log record.
    """
    client = make_client(GroqAuthFailProvider())
    with caplog.at_level(logging.DEBUG):
        response = client.post("/design", json={"idea": SENSITIVE_IDEA})
    assert response.status_code == 502
    assert SENSITIVE_IDEA not in response.text
    for record in caplog.records:
        assert SENSITIVE_IDEA not in record.getMessage()
