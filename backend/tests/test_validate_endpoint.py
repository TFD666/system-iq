"""
Tests for POST /validate -- no real network (FakeDecisionProvider / a
scripted DecisionProvider double, and a scripted LLM for revisions).
"""

import copy
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.decision.provider import (
    Alternative,
    Decision,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionResultSet,
    FakeDecisionProvider,
)
from app.design.sections import all_headings
from app.llm import LLMProvider, LLMResult
from app.main import app, get_decision_provider, get_provider

REQUIREMENTS = {
    "project_summary": "A to-do app for small teams.",
    "app_type": "web",
    "core_features": ["task creation"],
    "user_roles": ["user"],
    "expected_scale": {"users": None, "peak_requests_per_second": None, "data_volume": None},
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
}

DECISIONS = [
    {
        "id": "primary_database",
        "question": "Which database fits best?",
        "status": "accepted",
        "choice": "PostgreSQL",
        "probability": 0.9,
        "top_alternatives": [{"option": "PostgreSQL", "probability": 0.9}],
        "based_on_unknowns": False,
        "an_extra_field_from_the_future": "must be ignored",
    },
]


def _good_body() -> str:
    return " ".join(["word"] * 60)


def _design_markdown() -> str:
    return "\n\n".join(f"{heading}\n{_good_body()}" for heading in all_headings())


class _NullLLM(LLMProvider):
    """Never actually called when max_revisions=0 -- raises if it is."""
    def complete_json(self, system, user, max_tokens):
        raise AssertionError("complete_json must not be called by /validate")

    def complete_text(self, system, user, max_tokens):
        raise AssertionError("complete_text (a Groq call) must not happen when max_revisions=0")


class EchoLLM(LLMProvider):
    def complete_json(self, system, user, max_tokens):
        raise NotImplementedError

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        body = "\n\n".join(f"{h}\nRevised. {_good_body()}" for h in headings)
        return LLMResult(text=body, prompt_tokens=10, completion_tokens=20)


_PROBLEM_VAL_IDS = {
    "val_missing_component", "val_invented", "val_contradiction",
    "val_unneeded_complexity", "val_scale_overclaim", "val_incoherent",
}


class CountingDecisionProvider(DecisionProvider):
    """Forces every validation question to 'flagged'; counts decide() calls."""
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state, questions) -> DecisionResultSet:
        self.calls += 1
        decisions = {}
        for q in questions:
            p = 0.9 if q.id in _PROBLEM_VAL_IDS else 0.1
            decisions[q.id] = Decision(id=q.id, kind="noul", probability=p)
        return DecisionResultSet(
            decisions=decisions, model="scripted", input_tokens=3, output_tokens=2,
            billing_source="free", cost=0.0,
        )


class RateLimitDecisionProvider(DecisionProvider):
    def decide(self, state, questions) -> DecisionResultSet:
        raise DecisionRateLimitError(retry_after_seconds=5)


def _make_client(llm: LLMProvider, decision_provider: DecisionProvider) -> TestClient:
    app.dependency_overrides[get_provider] = lambda: llm
    app.dependency_overrides[get_decision_provider] = lambda: decision_provider
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _request_body(**overrides) -> dict:
    # Deep-copy the shared fixtures -- a test that mutates e.g. the
    # "requirements" dict in place must never leak that into other tests.
    body = {
        "requirements": copy.deepcopy(REQUIREMENTS),
        "decisions": copy.deepcopy(DECISIONS),
        "design_markdown": _design_markdown(),
        "max_revisions": 0,
    }
    body.update(overrides)
    return body


def test_max_revisions_zero_makes_no_llm_call_and_exactly_one_provider_request():
    provider = CountingDecisionProvider()
    client = _make_client(_NullLLM(), provider)
    response = client.post("/validate", json=_request_body(max_revisions=0))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "validated"
    assert provider.calls == 1
    assert body["meta"]["validation_calls"] == 1
    assert body["meta"]["validation_model"] == "scripted"
    assert body["revisions"] == []


def test_flagged_results_with_max_revisions_one_revises_only_mapped_sections():
    provider = CountingDecisionProvider()
    client = _make_client(EchoLLM(), provider)
    response = client.post("/validate", json=_request_body(max_revisions=1))

    assert response.status_code == 200
    body = response.json()
    assert provider.calls == 2  # 1 validate + 1 revalidate
    assert len(body["revisions"]) == 1
    revised = body["revisions"][0]["sections_revised"]
    assert 13 not in revised  # section 13 is never revised
    assert revised  # at least one real section got revised


def test_design_markdown_over_40000_chars_returns_422():
    client = _make_client(_NullLLM(), FakeDecisionProvider())
    huge_markdown = "## 1. Architecture overview\n" + ("word " * 10_000)
    response = client.post("/validate", json=_request_body(design_markdown=huge_markdown))
    assert response.status_code == 422


def test_body_over_100kb_returns_413():
    client = _make_client(_NullLLM(), FakeDecisionProvider())
    oversized_markdown = "## 1. Architecture overview\n" + ("x" * 39_000)
    body = _request_body(design_markdown=oversized_markdown)
    # Pad unknowns (a plain list field) to push the whole JSON body past 100KB
    # without touching the 40KB-capped design_markdown field.
    body["requirements"]["unknowns"] = ["x" * 1000 for _ in range(65)]
    response = client.post("/validate", json=body)
    assert response.status_code == 413


def test_extra_decision_fields_are_ignored():
    client = _make_client(_NullLLM(), FakeDecisionProvider())
    response = client.post("/validate", json=_request_body())
    assert response.status_code == 200


def test_rate_limit_during_validation_returns_skipped_not_an_error():
    client = _make_client(_NullLLM(), RateLimitDecisionProvider())
    response = client.post("/validate", json=_request_body(max_revisions=1))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["validation_status"] == "skipped"
    assert body["meta"]["validation_model"] is None  # never got a successful decide() call
    assert any("rate limited" in w for w in body["design_warnings"])
    assert body["design_markdown"]  # markdown still comes back, unmodified


class CrashingDecisionProvider(DecisionProvider):
    """Raises an unexpected error -- proves /validate converts ANY
    exception, not just the known Decision*Error types, into a clean 500."""
    def decide(self, state, questions) -> DecisionResultSet:
        raise RuntimeError("super secret design text that must never leak into a log or response")


def test_unexpected_error_during_validation_becomes_clean_500(caplog):
    client = _make_client(_NullLLM(), CrashingDecisionProvider())
    with caplog.at_level(logging.ERROR):
        response = client.post("/validate", json=_request_body())

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal error during validation. Try again."
    for record in caplog.records:
        assert "super secret design text" not in record.getMessage()
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)


def test_no_design_text_in_logs(caplog):
    provider = CountingDecisionProvider()
    client = _make_client(EchoLLM(), provider)
    with caplog.at_level(logging.DEBUG):
        response = client.post("/validate", json=_request_body(max_revisions=1))

    markdown = response.json()["design_markdown"]
    for record in caplog.records:
        message = record.getMessage()
        assert markdown not in message
        assert "Revised." not in message
