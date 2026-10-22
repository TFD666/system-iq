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
    LLMProvider,
    LLMResult,
    GroqProvider,
    RateLimitError,
)
from app.main import app, get_provider

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


# ── TestClient factory ─────────────────────────────────────────────────────────

def make_client(provider: LLMProvider) -> TestClient:
    """
    Override the FastAPI get_provider dependency with a fake, then build
    a TestClient.  The override is cleared after each test via the fixture.
    """
    app.dependency_overrides[get_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    # Ensure overrides do not leak between tests
    yield
    app.dependency_overrides.clear()


# ── /design endpoint tests ─────────────────────────────────────────────────────

def test_valid_idea_returns_200_and_stage_extracted():
    client = make_client(AlwaysGoodProvider())
    response = client.post("/design", json={"idea": "Build a to-do app"})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "extracted"
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
