"""
Tests for the decision provider – no real network calls anywhere.

Every HTTP interaction is mocked via unittest.mock.patch so httpx.post
returns a canned httpx.Response.  The Jev endpoint is never contacted.
time.sleep is also patched so tests run instantly.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from app.decision.provider import (
    Alternative,
    Decision,
    DecisionFormatError,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionResultSet,
    DecisionUnavailableError,
    FakeDecisionProvider,
    JevProvider,
    Question,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_KEY = "test-key-not-real"
FAKE_URL = "https://fake.test/v1/systemone"


def _env(
    key: str = FAKE_KEY,
    url: str = FAKE_URL,
    model: str = "jev-1.13-free",
) -> dict[str, str]:
    """Environment variables for JevProvider, pointing at a fake URL."""
    return {
        "OPENCODE_API_KEY": key,
        "JEV_BASE_URL": url,
        "JEV_MODEL": model,
    }


def _noul_question(qid: str = "needs_cache") -> Question:
    return Question(id=qid, kind="noul", text="Does this need caching?")


def _choice_question(qid: str = "tone") -> Question:
    return Question(
        id=qid,
        kind="choice",
        text="What is the tone of this message?",
        options=["angry", "calm", "excited"],
    )


def _score_question(qid: str = "urgency") -> Question:
    return Question(
        id=qid,
        kind="score",
        text="How urgent is this message?",
        options=["Can wait", "Needs attention this week", "Needs attention today"],
    )


def _make_provider(env: dict[str, str] | None = None) -> JevProvider:
    """Build a JevProvider with fake env vars."""
    with patch.dict("os.environ", env or _env(), clear=False):
        return JevProvider()


# -- Canned API response bodies (based on proven + docs examples) -----------

NOUL_RESPONSE: dict[str, Any] = {
    "model": "jev-1.13-free",
    "answers": {
        "needs_cache": {"type": "noul", "noul": 0.12},
    },
    "usage": {"input_tokens": 287, "output_tokens": 21},
}

# Choice response shape assumed from official docs:
# https://docs.typesafe.ai/api/system-one
CHOICE_RESPONSE: dict[str, Any] = {
    "model": "jev-1.13-free",
    "answers": {
        "tone": {
            "type": "choice",
            "choice": "calm",
            "confidence": 0.7,
            "probabilities": {
                "angry": 0.15,
                "calm": 0.80,
                "excited": 0.05,
            },
        },
    },
    "usage": {"input_tokens": 120, "output_tokens": 12},
}

# Score response shape assumed from official docs.
SCORE_RESPONSE: dict[str, Any] = {
    "model": "jev-1.13-free",
    "answers": {
        "urgency": {
            "type": "score",
            "score": 1.7,
            "confidence": 0.55,
            "legend": {
                "0": "Can wait",
                "1": "Needs attention this week",
                "2": "Needs attention today",
            },
            "probabilities": {
                "0": 0.1,
                "1": 0.1,
                "2": 0.8,
            },
        },
    },
    "usage": {"input_tokens": 120, "output_tokens": 12},
}


def _mock_response(
    body: dict[str, Any],
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Create a fake httpx.Response without hitting the network."""
    return httpx.Response(
        status_code=status,
        json=body,
        headers=headers or {},
    )


# ---------------------------------------------------------------------------
# Test: noul response parsed correctly (proven shape)
# ---------------------------------------------------------------------------


def test_noul_response_parsed():
    provider = _make_provider()
    question = _noul_question()

    mock_resp = _mock_response(NOUL_RESPONSE)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        result = provider.decide({"app": "test"}, [question])

    assert isinstance(result, DecisionResultSet)
    assert result.model == "jev-1.13-free"
    assert result.input_tokens == 287
    assert result.output_tokens == 21

    d = result.decisions["needs_cache"]
    assert d.kind == "noul"
    assert d.probability == pytest.approx(0.12)
    assert d.choice is None
    assert d.confidence is None
    assert d.alternatives == []


# ---------------------------------------------------------------------------
# Test: choice response parsed (docs-based fixture)
# ---------------------------------------------------------------------------


def test_choice_response_parsed():
    provider = _make_provider()
    question = _choice_question()

    mock_resp = _mock_response(CHOICE_RESPONSE)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        result = provider.decide({"msg": "hello"}, [question])

    d = result.decisions["tone"]
    assert d.kind == "choice"
    assert d.choice == "calm"
    # probability = the probability of the selected choice
    assert d.probability == pytest.approx(0.80)
    assert d.confidence == pytest.approx(0.7)
    # All three alternatives present
    alt_map = {a.option: a.probability for a in d.alternatives}
    assert alt_map["angry"] == pytest.approx(0.15)
    assert alt_map["calm"] == pytest.approx(0.80)
    assert alt_map["excited"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Test: score response parsed (docs-based fixture)
# ---------------------------------------------------------------------------


def test_score_response_parsed():
    provider = _make_provider()
    question = _score_question()

    mock_resp = _mock_response(SCORE_RESPONSE)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        result = provider.decide({"msg": "urgent"}, [question])

    d = result.decisions["urgency"]
    assert d.kind == "score"
    # 1.7 / 2 = 0.85 (normalised to 0..1)
    assert d.probability == pytest.approx(0.85)
    assert d.confidence == pytest.approx(0.55)
    # Most-probable level is "2" -> "Needs attention today"
    assert d.choice == "Needs attention today"
    # Alternatives
    alt_map = {a.option: a.probability for a in d.alternatives}
    assert alt_map["Can wait"] == pytest.approx(0.1)
    assert alt_map["Needs attention this week"] == pytest.approx(0.1)
    assert alt_map["Needs attention today"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Test: DecisionFormatError – missing question id in response
# ---------------------------------------------------------------------------


def test_missing_question_id_raises_format_error():
    provider = _make_provider()
    question = _noul_question("my_question")

    # Response answers don't include "my_question"
    bad_body = {
        "model": "jev-1.13-free",
        "answers": {
            "wrong_id": {"type": "noul", "noul": 0.5},
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    mock_resp = _mock_response(bad_body)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with pytest.raises(DecisionFormatError, match="my_question"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: DecisionFormatError – answer type doesn't match question kind
# ---------------------------------------------------------------------------


def test_wrong_answer_type_raises_format_error():
    provider = _make_provider()
    question = _noul_question()

    bad_body = {
        "model": "jev-1.13-free",
        "answers": {
            "needs_cache": {
                "type": "choice",
                "choice": "x",
                "confidence": 0.5,
                "probabilities": {"x": 1.0},
            },
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    mock_resp = _mock_response(bad_body)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with pytest.raises(DecisionFormatError, match="does not match"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: DecisionFormatError – probability out of range
# ---------------------------------------------------------------------------


def test_probability_out_of_range_raises_format_error():
    provider = _make_provider()
    question = _noul_question()

    bad_body = {
        "model": "jev-1.13-free",
        "answers": {
            "needs_cache": {"type": "noul", "noul": 1.5},  # > 1
        },
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    mock_resp = _mock_response(bad_body)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with pytest.raises(DecisionFormatError, match="outside 0..1"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: DecisionFormatError – malformed response (not a dict)
# ---------------------------------------------------------------------------


def test_malformed_response_raises_format_error():
    provider = _make_provider()
    question = _noul_question()

    # Return a list instead of a dict.
    mock_resp = httpx.Response(status_code=200, json=["not", "a", "dict"])
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with pytest.raises(DecisionFormatError, match="not a JSON object"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: DecisionUnavailableError – timeout
# ---------------------------------------------------------------------------


def test_timeout_raises_unavailable():
    provider = _make_provider()
    question = _noul_question()

    with patch(
        "app.decision.provider.httpx.post",
        side_effect=httpx.TimeoutException("timed out"),
    ):
        with pytest.raises(DecisionUnavailableError, match="reach"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: DecisionUnavailableError – network error
# ---------------------------------------------------------------------------


def test_connect_error_raises_unavailable():
    provider = _make_provider()
    question = _noul_question()

    with patch(
        "app.decision.provider.httpx.post",
        side_effect=httpx.ConnectError("refused"),
    ):
        with pytest.raises(DecisionUnavailableError):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: 429 with retry-after 5 → retries (mock sleep, assert called)
# ---------------------------------------------------------------------------


def test_429_short_retry_sleeps_and_retries():
    """When retry-after <= 60s, the provider sleeps and retries."""
    provider = _make_provider()
    question = _noul_question()

    resp_429 = _mock_response(
        {"error": {"type": "RateLimitError", "message": "slow down"}},
        status=429,
        headers={"retry-after": "5"},
    )
    resp_200 = _mock_response(NOUL_RESPONSE)

    with patch(
        "app.decision.provider.httpx.post",
        side_effect=[resp_429, resp_200],
    ):
        with patch("app.decision.provider.time.sleep") as mock_sleep:
            result = provider.decide({}, [question])

    # sleep was called with the retry-after value (5 seconds).
    mock_sleep.assert_called_once_with(5)
    # The final result is valid.
    assert result.decisions["needs_cache"].probability == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# Test: 429 with retry-after 43407 → does NOT sleep, raises immediately
# ---------------------------------------------------------------------------


def test_429_long_retry_raises_immediately():
    """When retry-after > 60s, raise at once without sleeping."""
    provider = _make_provider()
    question = _noul_question()

    resp_429 = _mock_response(
        {"error": {"type": "RateLimitError", "message": "wait"}},
        status=429,
        headers={"retry-after": "43407"},
    )

    with patch("app.decision.provider.httpx.post", return_value=resp_429):
        with patch("app.decision.provider.time.sleep") as mock_sleep:
            with pytest.raises(DecisionRateLimitError) as exc_info:
                provider.decide({}, [question])

    # sleep was NOT called.
    mock_sleep.assert_not_called()
    assert exc_info.value.retry_after_seconds == 43407
    assert exc_info.value.free_quota_exhausted is False


# ---------------------------------------------------------------------------
# Test: 429 + FreeUsageLimitError → free_quota_exhausted = True
# ---------------------------------------------------------------------------


def test_429_free_usage_limit_sets_flag():
    provider = _make_provider()
    question = _noul_question()

    resp_429 = _mock_response(
        {"type": "error", "error": {"type": "FreeUsageLimitError", "message": "..."}},
        status=429,
        headers={"retry-after": "43407"},
    )

    with patch("app.decision.provider.httpx.post", return_value=resp_429):
        with pytest.raises(DecisionRateLimitError) as exc_info:
            provider.decide({}, [question])

    assert exc_info.value.free_quota_exhausted is True
    assert exc_info.value.retry_after_seconds == 43407


# ---------------------------------------------------------------------------
# Test: DecisionUnavailableError – non-200, non-429 status
# ---------------------------------------------------------------------------


def test_http_500_raises_unavailable():
    provider = _make_provider()
    question = _noul_question()

    mock_resp = _mock_response({"error": "internal"}, status=500)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with pytest.raises(DecisionUnavailableError, match="500"):
            provider.decide({}, [question])


# ---------------------------------------------------------------------------
# Test: no state text, no question text, and no key in caplog output
# ---------------------------------------------------------------------------


def test_no_secrets_in_logs(caplog: pytest.LogCaptureFixture):
    """Neither state content, question text, response bodies, nor the
    API key should appear in log output at any level."""
    provider = _make_provider()
    question = _noul_question()

    # Trigger a log-producing path: HTTP 500.
    mock_resp = _mock_response({"error": "internal"}, status=500)
    with patch("app.decision.provider.httpx.post", return_value=mock_resp):
        with caplog.at_level(logging.DEBUG, logger="app.decision.provider"):
            with pytest.raises(DecisionUnavailableError):
                provider.decide(
                    {"secret_state": "my-private-data"},
                    [question],
                )

    log_text = caplog.text
    assert FAKE_KEY not in log_text, "API key leaked into logs"
    assert "my-private-data" not in log_text, "State content leaked into logs"
    assert "Does this need caching" not in log_text, "Question text leaked into logs"
    assert "secret_state" not in log_text, "State key leaked into logs"


# ---------------------------------------------------------------------------
# Test: FakeDecisionProvider returns canned decisions
# ---------------------------------------------------------------------------


def test_fake_provider_returns_canned():
    canned = {
        "q1": Decision(id="q1", kind="noul", probability=0.9),
    }
    fake = FakeDecisionProvider(canned=canned, model="fake-v1")

    questions = [
        Question(id="q1", kind="noul", text="Is it?"),
        Question(id="q2", kind="noul", text="Another?"),
    ]
    result = fake.decide({}, questions)

    assert result.model == "fake-v1"
    assert result.decisions["q1"].probability == pytest.approx(0.9)
    # q2 was not in canned -> gets the 0.5 default.
    assert result.decisions["q2"].probability == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test: JevProvider requires OPENCODE_API_KEY
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_value_error():
    with patch.dict("os.environ", {"JEV_BASE_URL": FAKE_URL}, clear=True):
        with pytest.raises(ValueError, match="OPENCODE_API_KEY"):
            JevProvider()


# ---------------------------------------------------------------------------
# Test: questions map is built correctly
# ---------------------------------------------------------------------------


def test_build_questions_map():
    questions = [
        _noul_question(),
        _choice_question(),
        _score_question(),
    ]
    qmap = JevProvider._build_questions_map(questions)

    # Noul: just type + instructions, no criteria.
    assert qmap["needs_cache"]["type"] == "noul"
    assert "criteria" not in qmap["needs_cache"]

    # Choice: criteria is {option: option}.
    assert qmap["tone"]["type"] == "choice"
    assert qmap["tone"]["criteria"] == {
        "angry": "angry",
        "calm": "calm",
        "excited": "excited",
    }

    # Score: criteria is an ordered list.
    assert qmap["urgency"]["type"] == "score"
    assert qmap["urgency"]["criteria"] == [
        "Can wait",
        "Needs attention this week",
        "Needs attention today",
    ]


# ---------------------------------------------------------------------------
# Test: DecisionProvider is abstract – cannot be instantiated directly
# ---------------------------------------------------------------------------


def test_decision_provider_is_abstract():
    with pytest.raises(TypeError):
        DecisionProvider()  # type: ignore[abstract]
