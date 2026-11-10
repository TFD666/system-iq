"""Tests for hosted access control."""

import hashlib
import hmac
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.hosted.access import (
    AccessManager,
    BadCode,
    CapacityReached,
    CodeLimitReached,
    IPLimitReached,
)
from app.hosted.jobs import JobManager
from app.main import app, get_access_manager, get_job_manager


# ── helpers ───────────────────────────────────────────────────────────────────


class _FakeRequest:
    def __init__(self, host="127.0.0.1", xff=None):
        self.client = type("C", (), {"host": host})()
        self.headers = {}
        if xff is not None:
            self.headers["x-forwarded-for"] = xff


class _FakeDesignResponse:
    def __init__(self, warnings=None):
        self.design_warnings = warnings or []

    def model_dump(self, mode="json"):
        return {
            "stage": "validated",
            "meta": {"decision_model": "fake", "input_tokens": 0, "output_tokens": 0},
            "design_markdown": "# Design",
            "design_warnings": self.design_warnings,
        }


class _FakeLLM:
    def complete(self, system, user, max_tokens=4096):
        return type("R", (), {"text": "# Design\nDone.", "usage": {"prompt_tokens": 1, "completion_tokens": 1}})()

    def complete_with_schema(self, system, user, schema, max_tokens=4096):
        return type("R", (), {"text": '{"sections":[]}', "usage": {"prompt_tokens": 1, "completion_tokens": 1}})()


class _FakeDecision:
    model = "fake"

    def evaluate(self, state, questions):
        from app.decision.schema import DecisionResult
        return DecisionResult(decisions=[], model=self.model, input_tokens=1, output_tokens=1)


def _make_access(clock=None, salt="test_salt"):
    return AccessManager(
        clock=clock or time.time,
        salt_factory=lambda: salt,
    )


def _expected_hash(salt, ip):
    return hashlib.sha256((salt + ip).encode()).hexdigest()


def _wait_done(mgr, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job and job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    return mgr.get(job_id)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "HOSTED", "ACCESS_CODES", "DAILY_DESIGN_CAP",
        "IP_DAILY_LIMIT", "TRUSTED_PROXY_HOPS", "SAMPLES_FILE", "DEMO_MODE",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    app.dependency_overrides.clear()
    for attr in ("access_manager", "job_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


# ── TestCheckCode ─────────────────────────────────────────────────────────────


class TestCheckCode:
    def test_valid_code_returns_label(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "alice:secret123:5")
        assert _make_access().check_code("secret123") == "alice"

    def test_invalid_code_returns_none(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "alice:secret123:5")
        assert _make_access().check_code("wrong") is None

    def test_empty_code_returns_none(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "alice:secret123:5")
        assert _make_access().check_code("") is None

    def test_no_codes_configured(self, monkeypatch):
        monkeypatch.delenv("ACCESS_CODES", raising=False)
        assert _make_access().check_code("anything") is None

    def test_multiple_codes(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "alice:aaa:5,bob:bbb:3")
        am = _make_access()
        assert am.check_code("aaa") == "alice"
        assert am.check_code("bbb") == "bob"
        assert am.check_code("ccc") is None

    def test_constant_time_all_codes_compared(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code_a:5,b:code_b:5,c:code_c:5")
        am = _make_access()
        calls = []
        orig = hmac.compare_digest

        def tracking(a, b):
            calls.append(1)
            return orig(a, b)

        monkeypatch.setattr(hmac, "compare_digest", tracking)
        am.check_code("code_b")
        assert len(calls) == 3


# ── TestClientIp ──────────────────────────────────────────────────────────────


class TestClientIp:
    def test_direct_hops_zero(self, monkeypatch):
        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
        am = _make_access(salt="s1")
        assert am.client_ip(_FakeRequest(host="10.0.0.1")) == _expected_hash("s1", "10.0.0.1")

    def test_xff_one_hop(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        am = _make_access(salt="s1")
        h = am.client_ip(_FakeRequest(host="proxy", xff="1.2.3.4, proxy"))
        assert h == _expected_hash("s1", "proxy")

    def test_xff_two_hops(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
        am = _make_access(salt="s1")
        h = am.client_ip(_FakeRequest(host="lb", xff="client, proxy, lb"))
        assert h == _expected_hash("s1", "proxy")

    def test_xff_short_falls_back(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "3")
        am = _make_access(salt="s1")
        h = am.client_ip(_FakeRequest(host="direct", xff="one"))
        assert h == _expected_hash("s1", "direct")

    def test_xff_missing_falls_back(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
        am = _make_access(salt="s1")
        h = am.client_ip(_FakeRequest(host="direct"))
        assert h == _expected_hash("s1", "direct")

    def test_different_salt_different_hash(self, monkeypatch):
        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
        req = _FakeRequest(host="1.2.3.4")
        h1 = _make_access(salt="a").client_ip(req)
        h2 = _make_access(salt="b").client_ip(req)
        assert h1 != h2


# ── TestDayRollover ───────────────────────────────────────────────────────────


class TestDayRollover:
    def test_new_day_resets_counters(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        t = [1700000000.0]
        salts = iter(["s1", "s2"])
        am = AccessManager(clock=lambda: t[0], salt_factory=lambda: next(salts))
        ip = am.client_ip(_FakeRequest(host="1.1.1.1"))
        am.reserve("a", ip)
        assert am.snapshot()["global_count"] == 1
        t[0] += 86400
        assert am.snapshot()["global_count"] == 0

    def test_new_day_clears_exhausted(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        t = [1700000000.0]
        am = AccessManager(clock=lambda: t[0], salt_factory=lambda: "s")
        am.set_exhausted("jev")
        assert am.is_exhausted("jev")
        t[0] += 86400
        am.snapshot()
        assert not am.is_exhausted("jev")

    def test_salt_changes_on_new_day(self, monkeypatch):
        monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
        t = [1700000000.0]
        salts = iter(["day1", "day2"])
        am = AccessManager(clock=lambda: t[0], salt_factory=lambda: next(salts))
        req = _FakeRequest(host="1.1.1.1")
        h1 = am.client_ip(req)
        t[0] += 86400
        h2 = am.client_ip(req)
        assert h1 != h2


# ── TestReserve ───────────────────────────────────────────────────────────────


class TestReserve:
    def test_returns_32_char_token(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        token = _make_access().reserve("a", "ip1")
        assert isinstance(token, str) and len(token) == 32

    def test_bad_code_raises(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        with pytest.raises(BadCode):
            _make_access().reserve(None, "ip")

    def test_ip_limit(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("IP_DAILY_LIMIT", "1")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        am.reserve("a", "ip1")
        with pytest.raises(IPLimitReached):
            am.reserve("a", "ip1")

    def test_code_limit(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:1")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        am.reserve("a", "ip1")
        with pytest.raises(CodeLimitReached):
            am.reserve("a", "ip2")

    def test_global_cap(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:10,b:code2:10")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "2")
        am = _make_access()
        am.reserve("a", "ip1")
        am.reserve("b", "ip2")
        with pytest.raises(CapacityReached) as exc_info:
            am.reserve("a", "ip3")
        assert exc_info.value.reason == "capacity"

    def test_groq_exhausted_raises_capacity(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:10")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        am.snapshot()  # initialize day so set_exhausted survives _maybe_reset
        am.set_exhausted("groq")
        with pytest.raises(CapacityReached) as exc_info:
            am.reserve("a", "ip1")
        assert exc_info.value.reason == "quota"


# ── TestRelease ───────────────────────────────────────────────────────────────


class TestRelease:
    def test_refund_on_failure(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        token = am.reserve("a", "ip1")
        am.release(token, app_failure=True)
        assert am.snapshot()["code_counts"]["a"] == 0

    def test_no_refund_on_success(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        token = am.reserve("a", "ip1")
        am.release(token, app_failure=False)
        assert am.snapshot()["code_counts"]["a"] == 1

    def test_global_count_not_refunded(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "10")
        am = _make_access()
        token = am.reserve("a", "ip1")
        am.release(token, app_failure=True)
        assert am.snapshot()["global_count"] == 1

    def test_unknown_token_is_noop(self):
        _make_access().release("nonexistent", app_failure=True)


# ── TestCapWarnings ───────────────────────────────────────────────────────────


class TestCapWarnings:
    def test_cap_80_and_hit_logged(self, monkeypatch, caplog):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "5")
        am = _make_access()
        with caplog.at_level(logging.WARNING, logger="app.hosted.access"):
            for i in range(5):
                am.reserve("a", f"ip_{i}")
        msgs = [r.message for r in caplog.records]
        assert any("CAP_80" in m for m in msgs)
        assert any("CAP_HIT" in m for m in msgs)

    def test_cap_warnings_once_per_day(self, monkeypatch, caplog):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "5")
        am = _make_access()
        with caplog.at_level(logging.WARNING, logger="app.hosted.access"):
            for i in range(5):
                am.reserve("a", f"ip_{i}")
        assert sum(1 for r in caplog.records if "CAP_80" in r.message) == 1
        assert sum(1 for r in caplog.records if "CAP_HIT" in r.message) == 1

    def test_warnings_log_only_numbers(self, monkeypatch, caplog):
        monkeypatch.setenv("ACCESS_CODES", "alice:secret_code_x:100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "5")
        am = _make_access()
        with caplog.at_level(logging.WARNING, logger="app.hosted.access"):
            for i in range(5):
                am.reserve("alice", f"ip_{i}")
        for r in caplog.records:
            assert "secret_code_x" not in r.message
            assert "alice" not in r.message


# ── TestSnapshot ──────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_structure(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:5")
        monkeypatch.setenv("IP_DAILY_LIMIT", "10")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "8")
        am = _make_access()
        am.reserve("a", "ip1")
        snap = am.snapshot()
        assert snap["global_count"] == 1
        assert snap["global_cap"] == 8
        assert snap["code_counts"] == {"a": 1}
        assert snap["exhausted"] == []
        assert snap["day"] is not None


# ── TestCheckOrder (endpoint) ─────────────────────────────────────────────────


class TestCheckOrder:
    def _hosted(self, monkeypatch, **extra):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "tester:valid_code:5")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        for k, v in extra.items():
            monkeypatch.setenv(k, v)

    def _wire(self, am, mgr):
        app.dependency_overrides[get_access_manager] = lambda: am
        app.dependency_overrides[get_job_manager] = lambda: mgr

    def _mgr(self, access=None):
        return JobManager(
            llm_factory=lambda: _FakeLLM(),
            decision_factory=lambda: _FakeDecision(),
            access=access,
        )

    def test_missing_code_403(self, monkeypatch):
        self._hosted(monkeypatch)
        am = _make_access()
        mgr = self._mgr()
        self._wire(am, mgr)
        resp = TestClient(app).post("/jobs", json={"idea": "test"})
        assert resp.status_code == 403
        mgr.stop()

    def test_valid_code_queues(self, monkeypatch):
        self._hosted(monkeypatch)
        am = _make_access()
        mgr = self._mgr(access=am)
        self._wire(am, mgr)
        resp = TestClient(app).post(
            "/jobs", json={"idea": "test"},
            headers={"X-Access-Code": "valid_code"},
        )
        assert resp.status_code == 202
        mgr.stop()

    def test_code_checked_before_mode(self, monkeypatch):
        self._hosted(monkeypatch, DEMO_MODE="off")
        am = _make_access()
        mgr = self._mgr()
        self._wire(am, mgr)
        client = TestClient(app)
        assert client.post("/jobs", json={"idea": "t"}).status_code == 403
        r2 = client.post(
            "/jobs", json={"idea": "t"},
            headers={"X-Access-Code": "valid_code"},
        )
        assert r2.status_code == 503
        mgr.stop()

    def test_ip_limit_429(self, monkeypatch):
        self._hosted(monkeypatch, IP_DAILY_LIMIT="1")
        am = _make_access()
        mgr = self._mgr()
        self._wire(am, mgr)
        client = TestClient(app)
        h = {"X-Access-Code": "valid_code"}
        assert client.post("/jobs", json={"idea": "a"}, headers=h).status_code == 202
        r2 = client.post("/jobs", json={"idea": "b"}, headers=h)
        assert r2.status_code == 429
        assert "network" in r2.json()["detail"].lower()
        mgr.stop()

    def test_code_limit_429(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "tester:valid_code:1")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        mgr = self._mgr()
        self._wire(am, mgr)
        client = TestClient(app)
        h = {"X-Access-Code": "valid_code"}
        assert client.post("/jobs", json={"idea": "a"}, headers=h).status_code == 202
        r2 = client.post("/jobs", json={"idea": "b"}, headers=h)
        assert r2.status_code == 429
        assert "access code" in r2.json()["detail"].lower()
        mgr.stop()

    def test_global_cap_returns_sample(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "a:ca:100,b:cb:100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "1")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        mgr = self._mgr(access=am)
        self._wire(am, mgr)
        client = TestClient(app)
        assert client.post("/jobs", json={"idea": "a"}, headers={"X-Access-Code": "ca"}).status_code == 202
        r2 = client.post("/jobs", json={"idea": "b"}, headers={"X-Access-Code": "cb"})
        assert r2.status_code == 200
        assert r2.json()["sample"] is True
        assert r2.json()["reason"] == "capacity"
        mgr.stop()

    def test_local_mode_no_code_needed(self, monkeypatch):
        monkeypatch.delenv("HOSTED", raising=False)
        mgr = self._mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        assert TestClient(app).post("/jobs", json={"idea": "test"}).status_code == 202
        mgr.stop()


# ── TestEndpointModes ─────────────────────────────────────────────────────────


class TestEndpointModes:
    def test_samples_with_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HOSTED", raising=False)
        monkeypatch.setenv("DEMO_MODE", "samples")
        sf = tmp_path / "samples.json"
        sf.write_text('[{"title":"Sample"}]')
        monkeypatch.setenv("SAMPLES_FILE", str(sf))
        mgr = JobManager(llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision())
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).post("/jobs", json={"idea": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["sample"] is True
        assert body["samples"] == [{"title": "Sample"}]
        mgr.stop()

    def test_samples_missing_file(self, monkeypatch):
        monkeypatch.delenv("HOSTED", raising=False)
        monkeypatch.setenv("DEMO_MODE", "samples")
        monkeypatch.setenv("SAMPLES_FILE", "/nonexistent.json")
        mgr = JobManager(llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision())
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).post("/jobs", json={"idea": "test"})
        assert resp.status_code == 200
        assert resp.json()["samples"] == []
        mgr.stop()

    def test_groq_exhausted_sample(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        am.snapshot()  # initialize day
        am.set_exhausted("groq")
        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = JobManager(llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision(), access=am)
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).post("/jobs", json={"idea": "t"}, headers={"X-Access-Code": "code"})
        assert resp.status_code == 200
        assert resp.json()["reason"] == "quota"
        mgr.stop()

    def test_queue_full_refunds_token(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = JobManager(
            llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision(),
            access=am, max_waiting=0,
        )
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).post("/jobs", json={"idea": "t"}, headers={"X-Access-Code": "code"})
        assert resp.status_code == 429
        assert am.snapshot()["code_counts"].get("a", 0) == 0
        mgr.stop()


# ── TestWorkerFallbacks ───────────────────────────────────────────────────────


class TestWorkerFallbacks:
    def _mgr_with(self, monkeypatch, pipeline_fn, access=None):
        monkeypatch.delenv("HOSTED", raising=False)
        mgr = JobManager(
            llm_factory=lambda: _FakeLLM(),
            decision_factory=lambda: _FakeDecision(),
            access=access,
        )
        mgr._try_pipeline = pipeline_fn
        return mgr

    def test_jev_flag_forces_llm_only(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()
        am.set_exhausted("jev")
        modes = []

        def pipe(idea, mode, on_stage):
            modes.append(mode)
            return _FakeDesignResponse()

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        _wait_done(mgr, jid)
        assert modes == ["llm_only"]
        mgr.stop()

    def test_decision_rate_limit_retries_llm_only(self, monkeypatch):
        from app.decision.provider import DecisionRateLimitError
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()
        calls = []

        def pipe(idea, mode, on_stage):
            calls.append(mode)
            if mode == "pipeline":
                raise DecisionRateLimitError(retry_after_seconds=60, free_quota_exhausted=True)
            return _FakeDesignResponse()

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        job = _wait_done(mgr, jid)
        assert job["status"] == "done"
        assert calls == ["pipeline", "llm_only"]
        assert am.is_exhausted("jev")
        mgr.stop()

    def test_groq_rate_limit_long_sets_flag(self, monkeypatch):
        from app.llm import RateLimitError
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()

        def pipe(idea, mode, on_stage):
            raise RateLimitError("slow", retry_after_seconds=600.0)

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        _wait_done(mgr, jid)
        assert am.is_exhausted("groq")
        mgr.stop()

    def test_groq_rate_limit_short_no_flag(self, monkeypatch):
        from app.llm import RateLimitError
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()

        def pipe(idea, mode, on_stage):
            raise RateLimitError("slow", retry_after_seconds=30.0)

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        _wait_done(mgr, jid)
        assert not am.is_exhausted("groq")
        mgr.stop()

    def test_validation_warning_sets_jev_flag(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()

        def pipe(idea, mode, on_stage):
            return _FakeDesignResponse(warnings=["validation skipped: rate limited"])

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        _wait_done(mgr, jid)
        assert am.is_exhausted("jev")
        mgr.stop()

    def test_fallback_reason_in_meta(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        am = _make_access()
        am.set_exhausted("jev")

        def pipe(idea, mode, on_stage):
            return _FakeDesignResponse()

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        jid, _ = mgr.submit("test")
        job = _wait_done(mgr, jid)
        assert job["result"]["meta"]["fallback"] == "llm_only (Jev quota exhausted)"
        mgr.stop()

    def test_app_failure_refunds_token(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        am = _make_access()

        def pipe(idea, mode, on_stage):
            raise RuntimeError("boom")

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        token = am.reserve("a", "ip1")
        jid, _ = mgr.submit("test", token=token)
        _wait_done(mgr, jid)
        assert am.snapshot()["code_counts"]["a"] == 0
        mgr.stop()

    def test_success_keeps_count(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        am = _make_access()

        def pipe(idea, mode, on_stage):
            return _FakeDesignResponse()

        mgr = self._mgr_with(monkeypatch, pipe, access=am)
        token = am.reserve("a", "ip1")
        jid, _ = mgr.submit("test", token=token)
        _wait_done(mgr, jid)
        assert am.snapshot()["code_counts"]["a"] == 1
        mgr.stop()


# ── TestSecurity ──────────────────────────────────────────────────────────────


class TestSecurity:
    def test_error_hides_codes(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "secret_label:secret_code:5")
        am = _make_access()
        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = JobManager(llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision())
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).post("/jobs", json={"idea": "t"}, headers={"X-Access-Code": "wrong"})
        body = json.dumps(resp.json())
        assert "secret_label" not in body
        assert "secret_code" not in body
        mgr.stop()

    def test_get_job_needs_no_code(self, monkeypatch):
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "a:code:100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = JobManager(
            llm_factory=lambda: _FakeLLM(), decision_factory=lambda: _FakeDecision(), access=am,
        )
        app.dependency_overrides[get_job_manager] = lambda: mgr
        client = TestClient(app)
        r = client.post("/jobs", json={"idea": "t"}, headers={"X-Access-Code": "code"})
        jid = r.json()["job_id"]
        assert client.get(f"/jobs/{jid}").status_code == 200
        mgr.stop()
