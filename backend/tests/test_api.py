"""
Tests for the FastAPI /design endpoint and GroqProvider 429 handling.

The GroqProvider 429 tests mock httpx.post and time.sleep so no real
network calls or real sleeping occur.
"""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractionError
from app.llm import (
    GROQ_API_URL,
    MAX_RATE_LIMIT_RETRIES,
    GroqAuthError,
    LLMProvider,
    LLMResult,
    GroqProvider,
    RateLimitError,
)
from app.decision.provider import (
    DecisionAuthError,
    DecisionProvider,
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
    # Stage is now "decided" because the endpoint always runs extraction + decisions.
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
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

    # sleep was called once with the capped retry-after value
    mock_sleep.assert_called_once_with(2)
    # httpx.post was called twice total
    assert mock_post.call_count == 2
    # The successful response's token counts come through
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 50


def test_429_three_times_raises_rate_limit_error(groq_provider):
    """
    Three 429s in a row (attempt 0, 1, 2) exhaust MAX_RATE_LIMIT_RETRIES (2)
    and must raise RateLimitError. sleep is called for the first two 429s only.
    """
    # MAX_RATE_LIMIT_RETRIES = 2, so loop runs 3 times (attempts 0, 1, 2)
    responses = [_make_429_response()] * (MAX_RATE_LIMIT_RETRIES + 1)

    with patch("app.llm.httpx.post", side_effect=responses), \
         patch("app.llm.time.sleep") as mock_sleep:

        with pytest.raises(RateLimitError):
            groq_provider.complete_json(
                system="sys", user="usr", max_tokens=100
            )

    # sleep is called for attempt 0 and 1 only; attempt 2 raises instead
    assert mock_sleep.call_count == MAX_RATE_LIMIT_RETRIES


@pytest.mark.parametrize("status", [401, 403])
def test_groq_401_and_403_raise_auth_error(groq_provider, status):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = {}

    with patch("app.llm.httpx.post", return_value=resp):
        with pytest.raises(GroqAuthError, match=str(status)):
            groq_provider.complete_json(system="sys", user="usr", max_tokens=100)


# ── log-leak tests ─────────────────────────────────────────────────────────────

import logging

SENSITIVE_IDEA = "my secret idea with sk-abcdefghijklmnopqrstuvwxyz1234"


def test_idea_text_does_not_appear_in_logs_on_success(caplog):
    """
    After a successful /design call, the idea text must not appear in any
    log record at any level.
    """
    client = make_client(AlwaysGoodProvider())
    with caplog.at_level(logging.DEBUG):
        response = client.post("/design", json={"idea": SENSITIVE_IDEA})
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
