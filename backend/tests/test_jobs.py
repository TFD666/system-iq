"""
Tests for POST /jobs, GET /jobs/{job_id} and the JobManager.
No network, fake LLM/decision provider, fake clock throughout.
"""

import json
import logging
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.design import TokenBudget
from app.hosted.jobs import JobManager, JobQueueFull
from app.llm import LLMProvider, LLMResult, LLMUnavailableError, RateLimitError
from app.decision.provider import (
    Alternative,
    Decision,
    DecisionProvider,
    DecisionResultSet,
)
from app.main import app, get_job_manager


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
    def complete_json(self, system, user, max_tokens):
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        filler = " ".join(["Some generated section text."] * 21)
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)


class _SimpleDecisionProvider(DecisionProvider):
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


class _GatedProvider(LLMProvider):
    """Blocks in complete_json until gate is set."""

    def __init__(self, started_event, gate_event):
        self._started = started_event
        self._gate = gate_event

    def complete_json(self, system, user, max_tokens):
        self._started.set()
        self._gate.wait()
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system, user, max_tokens):
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        filler = " ".join(["Some generated section text."] * 21)
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)


class _WritingGatedProvider(LLMProvider):
    """Passes extraction, blocks in complete_text (writing stage)."""

    def __init__(self, writing_started, writing_gate):
        self._writing_started = writing_started
        self._writing_gate = writing_gate

    def complete_json(self, system, user, max_tokens):
        return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

    def complete_text(self, system, user, max_tokens):
        self._writing_started.set()
        self._writing_gate.wait()
        headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
        filler = " ".join(["Some generated section text."] * 21)
        body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
        return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_clock():
    t = [0.0]

    def clock():
        return t[0]

    def advance(seconds):
        t[0] += seconds

    def sleep(seconds):
        t[0] += seconds

    return clock, advance, sleep


def _wait_done(manager, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job and job["status"] in ("done", "failed"):
            return job
    raise TimeoutError(f"Job {job_id} did not finish in {timeout}s")


def _make_manager(
    llm_factory=None,
    decision_factory=None,
    clock=None,
    sleep_fn=None,
    redact=None,
    budget=None,
    max_waiting=2,
    ttl_seconds=3600,
):
    if clock is None:
        clock, _, sleep_fn = _fake_clock()
    if budget is None:
        budget = TokenBudget(clock=clock, sleep=sleep_fn or (lambda _s: None))
    return JobManager(
        llm_factory=llm_factory or _GoodProvider,
        decision_factory=decision_factory or _SimpleDecisionProvider,
        budget=budget,
        clock=clock,
        redact=redact,
        max_waiting=max_waiting,
        ttl_seconds=ttl_seconds,
    )


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.clear()
    if hasattr(app.state, "job_manager"):
        del app.state.job_manager


# ── tests ────────────────────────────────────────────────────────────────────


def test_post_jobs_202_and_reaches_done(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.post("/jobs", json={"idea": "Build a to-do app"})
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    assert body["position"] >= 1

    job = _wait_done(mgr, body["job_id"])
    assert job["status"] == "done"
    assert "result" in job
    result_keys = set(job["result"].keys())
    for key in ("stage", "requirements", "design_markdown", "meta"):
        assert key in result_keys

    mgr.stop()


def test_status_progression_queued_running_done(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    started = threading.Event()
    gate = threading.Event()

    mgr = _make_manager(llm_factory=lambda: _GatedProvider(started, gate))

    j1_id, _ = mgr.submit("idea 1")
    started.wait(timeout=5)

    j2_id, p2 = mgr.submit("idea 2")
    j3_id, p3 = mgr.submit("idea 3")

    assert p2 == 1
    assert p3 == 2
    assert mgr.get(j2_id)["status"] == "queued"
    assert mgr.get(j2_id)["position"] == 1
    assert mgr.get(j3_id)["status"] == "queued"
    assert mgr.get(j3_id)["position"] == 2

    j1 = mgr.get(j1_id)
    assert j1["status"] == "running"
    assert j1["position"] is None

    gate.set()
    _wait_done(mgr, j1_id)
    _wait_done(mgr, j2_id)
    _wait_done(mgr, j3_id)

    assert mgr.get(j1_id)["status"] == "done"
    assert mgr.get(j2_id)["status"] == "done"
    assert mgr.get(j3_id)["status"] == "done"

    mgr.stop()


def test_running_job_shows_stage_and_group_detail(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    writing_started = threading.Event()
    writing_gate = threading.Event()

    mgr = _make_manager(
        llm_factory=lambda: _WritingGatedProvider(writing_started, writing_gate),
    )

    j_id, _ = mgr.submit("Build a to-do app")
    writing_started.wait(timeout=10)

    job = mgr.get(j_id)
    assert job["status"] == "running"
    assert job["stage"] == "writing"
    assert isinstance(job["detail"], dict)
    assert job["detail"]["group"] == 1
    assert job["detail"]["of"] == 4

    writing_gate.set()
    _wait_done(mgr, j_id)
    assert mgr.get(j_id)["status"] == "done"

    mgr.stop()


def test_fourth_submission_rejected_429(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    started = threading.Event()
    gate = threading.Event()

    mgr = _make_manager(
        llm_factory=lambda: _GatedProvider(started, gate), max_waiting=2,
    )
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    r1 = client.post("/jobs", json={"idea": "idea 1"})
    assert r1.status_code == 202
    started.wait(timeout=5)

    r2 = client.post("/jobs", json={"idea": "idea 2"})
    assert r2.status_code == 202
    r3 = client.post("/jobs", json={"idea": "idea 3"})
    assert r3.status_code == 202

    r4 = client.post("/jobs", json={"idea": "idea 4"})
    assert r4.status_code == 429
    assert "busy" in r4.json()["detail"].lower()

    gate.set()
    mgr.stop()


def test_unknown_job_id_404(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.get("/jobs/nonexistent123")
    assert resp.status_code == 404
    detail = resp.json()["detail"].lower()
    assert "unknown" in detail or "expired" in detail

    mgr.stop()


def test_idea_too_long_422(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("MAX_IDEA_CHARS", "50")
    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.post("/jobs", json={"idea": "x" * 51})
    assert resp.status_code == 422
    assert "max 50 characters" in resp.json()["detail"]

    mgr.stop()


def test_expired_finished_job_404(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    clock, advance, sleep = _fake_clock()
    mgr = _make_manager(clock=clock, sleep_fn=sleep, ttl_seconds=100)

    j_id, _ = mgr.submit("Build a to-do app")
    _wait_done(mgr, j_id)
    assert mgr.get(j_id) is not None

    advance(101)
    assert mgr.get(j_id) is None

    mgr.stop()


def test_unfinished_job_not_purged(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    started = threading.Event()
    gate = threading.Event()
    clock, advance, sleep = _fake_clock()

    mgr = _make_manager(
        llm_factory=lambda: _GatedProvider(started, gate),
        clock=clock, sleep_fn=sleep, ttl_seconds=100,
    )

    j_id, _ = mgr.submit("Build a to-do app")
    started.wait(timeout=5)

    advance(200)

    job = mgr.get(j_id)
    assert job is not None
    assert job["status"] == "running"

    gate.set()
    _wait_done(mgr, j_id)
    mgr.stop()


@pytest.mark.parametrize("exc_cls,exc_args,expected_status", [
    (RateLimitError, ("rate limited",), 429),
    (LLMUnavailableError, ("gone",), 503),
    (RuntimeError, ("boom",), 500),
])
def test_failing_job_mapped_and_next_runs(
    monkeypatch, exc_cls, exc_args, expected_status,
):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    should_fail = [True]

    class _SwitchProvider(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            if should_fail[0]:
                raise exc_cls(*exc_args)
            return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            filler = " ".join(["Some generated section text."] * 21)
            body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
            return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)

    mgr = _make_manager(llm_factory=_SwitchProvider)

    j1_id, _ = mgr.submit("idea 1")
    j1 = _wait_done(mgr, j1_id)
    assert j1["status"] == "failed"
    assert j1["error"]["status"] == expected_status

    should_fail[0] = False
    j2_id, _ = mgr.submit("idea 2")
    j2 = _wait_done(mgr, j2_id)
    assert j2["status"] == "done"

    mgr.stop()


def test_idea_text_never_in_status_json(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    started = threading.Event()
    gate = threading.Event()

    secret_idea = "my super secret idea with sk-12345 and password123"

    mgr = _make_manager(llm_factory=lambda: _GatedProvider(started, gate))

    j_id, _ = mgr.submit(secret_idea)
    started.wait(timeout=5)

    job_running = mgr.get(j_id)
    assert secret_idea not in json.dumps(job_running)

    gate.set()
    _wait_done(mgr, j_id)

    job_done = mgr.get(j_id)
    assert secret_idea not in json.dumps(job_done)

    mgr.stop()


def test_idea_text_never_in_logs(monkeypatch, caplog):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    secret_idea = "my super secret idea with sk-12345 and password123"
    mgr = _make_manager()

    with caplog.at_level(logging.DEBUG):
        j_id, _ = mgr.submit(secret_idea)
        _wait_done(mgr, j_id)

    for record in caplog.records:
        assert secret_idea not in record.getMessage()

    mgr.stop()


def test_redaction_applied_in_worker(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    received_texts = []

    class _CapturingProvider(LLMProvider):
        def complete_json(self, system, user, max_tokens):
            received_texts.append(user)
            return LLMResult(text=VALID_JSON, prompt_tokens=10, completion_tokens=20)

        def complete_text(self, system, user, max_tokens):
            headings = re.findall(r"^## \d+\..*$", system, re.MULTILINE)
            filler = " ".join(["Some generated section text."] * 21)
            body = "\n\n".join(f"{heading}\n{filler}" for heading in headings)
            return LLMResult(text=body, prompt_tokens=15, completion_tokens=25)

    secret = "test@example.com"

    def fake_redact(text):
        return text.replace(secret, "[REDACTED]"), [("email", 1)]

    mgr = _make_manager(llm_factory=_CapturingProvider, redact=fake_redact)

    j_id, _ = mgr.submit(f"Build app for {secret}")
    _wait_done(mgr, j_id)

    assert len(received_texts) > 0
    for t in received_texts:
        assert secret not in t
    assert any("[REDACTED]" in t for t in received_texts)

    mgr.stop()


def test_two_jobs_share_budget(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    clock, _, sleep = _fake_clock()
    budget = TokenBudget(clock=clock, sleep=sleep)
    record_calls = [0]
    original_record = budget.record

    def counting_record(total, output):
        record_calls[0] += 1
        original_record(total, output)

    budget.record = counting_record

    mgr = _make_manager(clock=clock, sleep_fn=sleep, budget=budget)

    j1_id, _ = mgr.submit("idea 1")
    _wait_done(mgr, j1_id)
    after_first = record_calls[0]

    j2_id, _ = mgr.submit("idea 2")
    _wait_done(mgr, j2_id)
    after_second = record_calls[0]

    assert after_first > 0
    assert after_second > after_first

    mgr.stop()


def test_jobs_work_when_hosted_while_design_blocked(monkeypatch):
    monkeypatch.setenv("HOSTED", "1")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("ACCESS_CODES", "test:testcode:100")
    monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
    monkeypatch.setenv("IP_DAILY_LIMIT", "100")

    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr

    from app.main import get_provider, get_decision_provider, get_access_manager
    from app.hosted.access import AccessManager

    am = AccessManager()
    app.dependency_overrides[get_access_manager] = lambda: am
    app.dependency_overrides[get_provider] = _GoodProvider
    app.dependency_overrides[get_decision_provider] = _SimpleDecisionProvider

    client = TestClient(app)

    design_resp = client.post("/design", json={"idea": "Build a to-do app"})
    assert design_resp.status_code == 404

    jobs_resp = client.post(
        "/jobs", json={"idea": "Build a to-do app"},
        headers={"X-Access-Code": "testcode"},
    )
    assert jobs_resp.status_code == 202

    j_id = jobs_resp.json()["job_id"]
    _wait_done(mgr, j_id)

    get_resp = client.get(f"/jobs/{j_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "done"

    mgr.stop()


def test_demo_mode_off_503(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "off")

    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.post("/jobs", json={"idea": "Build a to-do app"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Demo paused."

    mgr.stop()


def test_demo_mode_samples_returns_sample(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "samples")

    mgr = _make_manager()
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.post("/jobs", json={"idea": "Build a to-do app"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample"] is True
    assert body["reason"] == "samples mode"
    assert isinstance(body["samples"], list)

    mgr.stop()


def test_llm_only_mode_zero_decision_calls(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "llm_only")

    class _ExplodingDecisionProvider(DecisionProvider):
        def decide(self, state, questions):
            raise AssertionError("decision provider must not be called")

    mgr = _make_manager(decision_factory=_ExplodingDecisionProvider)

    j_id, _ = mgr.submit("Build a to-do app")
    j = _wait_done(mgr, j_id)

    assert j["status"] == "done"

    mgr.stop()


def test_expired_job_via_http_404(monkeypatch):
    monkeypatch.delenv("HOSTED", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    clock, advance, sleep = _fake_clock()
    mgr = _make_manager(clock=clock, sleep_fn=sleep, ttl_seconds=100)
    app.dependency_overrides[get_job_manager] = lambda: mgr
    client = TestClient(app)

    resp = client.post("/jobs", json={"idea": "Build a to-do app"})
    j_id = resp.json()["job_id"]
    _wait_done(mgr, j_id)

    advance(101)

    get_resp = client.get(f"/jobs/{j_id}")
    assert get_resp.status_code == 404

    mgr.stop()
