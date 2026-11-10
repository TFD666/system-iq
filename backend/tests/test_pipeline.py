"""
Tests for backend/app/pipeline.py -- the reusable run_pipeline function.
No network, fake LLM and fake decision provider throughout.
"""

import json
import re
import threading
from unittest.mock import MagicMock

import pytest

from app.llm import LLMProvider, LLMResult
from app.decision.provider import (
    Alternative,
    Decision,
    DecisionProvider,
    DecisionResultSet,
    FakeDecisionProvider,
)
from app.pipeline import run_pipeline
from app.schemas import DesignRequest


# ── shared fixture data ──────────────────────────────────────────────────────

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


# ── fake providers ───────────────────────────────────────────────────────────

class _GoodProvider(LLMProvider):
    """Succeeds at extraction AND at writing the design."""
    def complete_json(self, system, user, max_tokens):
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        filler = " ".join(["Some generated section text."] * 21)
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)


class _SimpleDecisionProvider(DecisionProvider):
    """Accepted choice / no noul for every question; all validation passes."""
    def decide(self, state, questions):
        decisions = {}
        for q in questions:
            if q.kind == "choice":
                option = q.options[0] if q.options else "X"
                decisions[q.id] = Decision(
                    id=q.id, kind="choice", choice=option, probability=0.9,
                    alternatives=[Alternative(option=option, probability=0.9)],
                )
            else:
                decisions[q.id] = Decision(id=q.id, kind="noul", probability=0.5)
        return DecisionResultSet(
            decisions=decisions, model="test", input_tokens=5, output_tokens=5,
            billing_source="free", cost=0.0,
        )


# ── callback order tests ────────────────────────────────────────────────────

def test_callback_order_full_validate_pipeline():
    stages = []
    def on_stage(name, detail):
        stages.append((name, detail))

    request = DesignRequest(idea="Build a to-do app", stage="validate")
    run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=on_stage)

    names = [s[0] for s in stages]
    assert names[0] == "extracting"
    assert names[1] == "deciding"
    assert "writing" in names
    assert "validating" in names
    assert names[-1] == "done"

    writing_stages = [s for s in stages if s[0] == "writing"]
    assert len(writing_stages) == 4
    for i, (_, detail) in enumerate(writing_stages, 1):
        assert detail == {"group": i, "of": 4}


def test_callback_order_llm_only():
    stages = []
    def on_stage(name, detail):
        stages.append((name, detail))

    request = DesignRequest(idea="Build a to-do app", mode="llm_only")
    run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=on_stage)

    names = [s[0] for s in stages]
    assert "extracting" in names
    assert "deciding" not in names
    assert "validating" not in names
    assert "writing" in names
    assert names[-1] == "done"


def test_callback_order_stage_extract():
    stages = []
    def on_stage(name, detail):
        stages.append((name, detail))

    request = DesignRequest(idea="Build a to-do app", stage="extract")
    run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=on_stage)

    names = [s[0] for s in stages]
    assert names == ["extracting", "done"]


def test_callback_order_stage_decide():
    stages = []
    def on_stage(name, detail):
        stages.append((name, detail))

    request = DesignRequest(idea="Build a to-do app", stage="decide")
    run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=on_stage)

    names = [s[0] for s in stages]
    assert names == ["extracting", "deciding", "done"]


# ── raising callback does not break the run ──────────────────────────────────

def test_raising_callback_does_not_break_pipeline():
    def exploding_callback(name, detail):
        raise ValueError("boom")

    request = DesignRequest(idea="Build a to-do app", stage="validate")
    response = run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=exploding_callback)
    assert response.stage == "validated"
    assert response.design_markdown


# ── two concurrent calls give independent results ────────────────────────────

def test_concurrent_calls_independent_budgets():
    results = [None, None]
    errors = [None, None]

    def run_one(index):
        try:
            request = DesignRequest(idea="Build a to-do app", stage="design")
            results[index] = run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider())
        except Exception as e:
            errors[index] = e

    t0 = threading.Thread(target=run_one, args=(0,))
    t1 = threading.Thread(target=run_one, args=(1,))
    t0.start()
    t1.start()
    t0.join()
    t1.join()

    assert errors[0] is None, f"Thread 0 raised: {errors[0]}"
    assert errors[1] is None, f"Thread 1 raised: {errors[1]}"
    assert results[0].stage == "designed"
    assert results[1].stage == "designed"
    assert results[0].design_markdown
    assert results[1].design_markdown


# ── callback never receives idea or design text ─────────────────────────────

def test_callback_never_receives_idea_or_design_text():
    all_args = []
    def on_stage(name, detail):
        all_args.append((name, detail))

    idea = "Build a super secret to-do app with sk-12345"
    request = DesignRequest(idea=idea, stage="validate")
    response = run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider(), on_stage=on_stage)

    for name, detail in all_args:
        assert idea not in str(name)
        assert idea not in str(detail)
        if response.design_markdown:
            assert response.design_markdown not in str(detail)
        if detail is not None:
            for v in detail.values():
                assert idea not in str(v)
                if response.design_markdown:
                    assert response.design_markdown not in str(v)


# ── /design response identical for fixed fake setup ─────────────────────────

def test_pipeline_response_matches_http_response():
    """run_pipeline produces the same JSON as the /design endpoint for
    a fixed fake setup (the same providers)."""
    from fastapi.testclient import TestClient
    from app.main import app, get_provider, get_decision_provider

    llm = _GoodProvider()
    dp = _SimpleDecisionProvider()

    app.dependency_overrides[get_provider] = lambda: llm
    app.dependency_overrides[get_decision_provider] = lambda: dp
    try:
        client = TestClient(app)
        http_response = client.post("/design", json={"idea": "Build a to-do app", "stage": "design"})
        assert http_response.status_code == 200
        http_json = http_response.json()
    finally:
        app.dependency_overrides.clear()

    request = DesignRequest(idea="Build a to-do app", stage="design")
    pipeline_response = run_pipeline(request, _GoodProvider(), _SimpleDecisionProvider())
    pipeline_json = pipeline_response.model_dump()

    assert http_json["stage"] == pipeline_json["stage"]
    assert http_json["requirements"] == pipeline_json["requirements"]
    assert http_json["decisions"] == pipeline_json["decisions"]
    assert set(http_json.keys()) == set(pipeline_json.keys())
