"""Tests for admin stats, exception handler, log filter, samples path, UTF-8."""

import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.hosted.access import AccessManager
from app.hosted.jobs import JobManager
from app.main import app, get_access_manager, get_job_manager


# ── helpers ───────────────────────────────────────────────────────────────────


class _FakeLLM:
    def complete(self, system, user, max_tokens=4096):
        return type("R", (), {
            "text": "# D",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })()

    def complete_with_schema(self, system, user, schema, max_tokens=4096):
        return type("R", (), {
            "text": "{}",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })()


class _FakeDecision:
    model = "fake"

    def evaluate(self, state, questions):
        from app.decision.schema import DecisionResult
        return DecisionResult(
            decisions=[], model="fake", input_tokens=1, output_tokens=1,
        )


def _make_access():
    return AccessManager(salt_factory=lambda: "test_salt")


def _make_mgr(access=None):
    return JobManager(
        llm_factory=lambda: _FakeLLM(),
        decision_factory=lambda: _FakeDecision(),
        access=access,
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "HOSTED", "ACCESS_CODES", "DAILY_DESIGN_CAP", "IP_DAILY_LIMIT",
        "TRUSTED_PROXY_HOPS", "SAMPLES_FILE", "DEMO_MODE", "ADMIN_TOKEN",
        "GROQ_API_KEY", "OPENCODE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
    app.dependency_overrides.clear()
    for attr in ("access_manager", "job_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


# ── Admin stats ───────────────────────────────────────────────────────────────


class TestAdminStats:
    def _setup(self, monkeypatch, token="admin_secret_tok"):
        monkeypatch.setenv("ADMIN_TOKEN", token)

    def test_good_token(self, monkeypatch):
        self._setup(monkeypatch)
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        client = TestClient(app)
        resp = client.get(
            "/admin/stats", headers={"X-Admin-Token": "admin_secret_tok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "demo_mode", "day_utc", "designs_today", "daily_cap", "by_label",
            "ip_hashes_today", "failed_today", "jobs", "groq_exhausted",
            "jev_exhausted", "queue_length", "uptime_minutes",
        ):
            assert key in body, f"missing {key}"
        mgr.stop()

    def test_wrong_token_403(self, monkeypatch):
        self._setup(monkeypatch)
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Forbidden."
        mgr.stop()

    def test_no_token_header_403(self, monkeypatch):
        self._setup(monkeypatch)
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get("/admin/stats")
        assert resp.status_code == 403
        mgr.stop()

    def test_admin_token_unset_404(self, monkeypatch):
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "anything"},
        )
        assert resp.status_code == 404
        mgr.stop()

    def test_admin_token_non_ascii_no_type_error(self, monkeypatch):
        """Non-ASCII str in compare_digest raises TypeError; UTF-8 encoding prevents it."""
        import hmac as hmac_mod
        with pytest.raises(TypeError):
            hmac_mod.compare_digest("café", "cafe")
        result = hmac_mod.compare_digest(
            "café".encode("utf-8"), "cafe".encode("utf-8"),
        )
        assert result is False

    def test_counts_after_jobs(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "a:code_val:100")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")

        am = _make_access()
        am.snapshot()
        t1 = am.reserve("a", "ip1")
        am.release(t1, app_failure=True)
        t2 = am.reserve("a", "ip2")
        am.release(t2, app_failure=False)

        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = _make_mgr(access=am)
        app.dependency_overrides[get_job_manager] = lambda: mgr

        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "admin_secret_tok"},
        )
        body = resp.json()
        assert body["designs_today"] == 2
        assert body["failed_today"] == 1
        assert body["ip_hashes_today"] == 2
        assert body["by_label"] == {"a": 1}
        mgr.stop()

    def test_no_secrets_in_stats(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.setenv("HOSTED", "1")
        monkeypatch.setenv("ACCESS_CODES", "secret_label:secret_code_xyz:5")
        monkeypatch.setenv("DAILY_DESIGN_CAP", "100")
        monkeypatch.setenv("IP_DAILY_LIMIT", "100")
        am = _make_access()
        am.snapshot()
        am.reserve("secret_label", "ip_hash_abc")
        app.dependency_overrides[get_access_manager] = lambda: am
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "admin_secret_tok"},
        )
        text = json.dumps(resp.json())
        assert "secret_code_xyz" not in text
        assert "ip_hash_abc" not in text
        mgr.stop()

    def test_job_counts_structure(self, monkeypatch):
        self._setup(monkeypatch)
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "admin_secret_tok"},
        )
        jobs = resp.json()["jobs"]
        assert set(jobs.keys()) == {"queued", "running", "done", "failed"}
        mgr.stop()

    def test_local_mode_works(self, monkeypatch):
        self._setup(monkeypatch)
        mgr = _make_mgr()
        app.dependency_overrides[get_job_manager] = lambda: mgr
        resp = TestClient(app).get(
            "/admin/stats", headers={"X-Admin-Token": "admin_secret_tok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["designs_today"] == 0
        assert body["day_utc"] is None
        mgr.stop()


# ── Exception handler ─────────────────────────────────────────────────────────


class TestExceptionHandler:
    def test_hides_details(self):
        def bad():
            raise ValueError("super secret error details")

        app.dependency_overrides[get_job_manager] = bad
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/jobs/xyz")
        assert resp.status_code == 500
        body = resp.json()
        assert body == {"detail": "Internal error. Try again."}
        assert "secret" not in json.dumps(body)

    def test_logs_class_name_and_template(self, caplog):
        def bad():
            raise TypeError("nope")

        app.dependency_overrides[get_job_manager] = bad
        with caplog.at_level(logging.ERROR, logger="app.main"):
            TestClient(app, raise_server_exceptions=False).get(
                "/jobs/some_id_value",
            )
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("TypeError" in r.message for r in errors)
        assert any("/jobs/{job_id}" in r.message for r in errors)
        assert not any("some_id_value" in r.message for r in errors)


# ── Log filter ────────────────────────────────────────────────────────────────


class TestLogFilter:
    def test_drops_access_code(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:my_secret_code_abc:5")
        from app.logging_setup import _SecretFilter
        f = _SecretFilter()
        rec = logging.LogRecord(
            "t", logging.INFO, "", 0, "leaked my_secret_code_abc", (), None,
        )
        assert f.filter(rec) is False

    def test_drops_api_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_testkey_1234abcd")
        from app.logging_setup import _SecretFilter
        f = _SecretFilter()
        rec = logging.LogRecord(
            "t", logging.INFO, "", 0, "key is gsk_testkey_1234abcd", (), None,
        )
        assert f.filter(rec) is False

    def test_drops_admin_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", "admin_tok_12345678")
        from app.logging_setup import _SecretFilter
        f = _SecretFilter()
        rec = logging.LogRecord(
            "t", logging.INFO, "", 0, "token admin_tok_12345678", (), None,
        )
        assert f.filter(rec) is False

    def test_keeps_normal(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:longcode12345:5")
        from app.logging_setup import _SecretFilter
        f = _SecretFilter()
        rec = logging.LogRecord(
            "t", logging.INFO, "", 0, "normal log message", (), None,
        )
        assert f.filter(rec) is True

    def test_ignores_short_secrets(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "short")
        from app.logging_setup import _SecretFilter
        f = _SecretFilter()
        rec = logging.LogRecord(
            "t", logging.INFO, "", 0, "contains short", (), None,
        )
        assert f.filter(rec) is True

    def test_uvicorn_access_level(self):
        from app.logging_setup import configure_logging
        configure_logging()
        assert logging.getLogger("uvicorn.access").level == logging.WARNING


# ── Samples path ──────────────────────────────────────────────────────────────


class TestSamplesPath:
    def test_repo_root_resolution(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.main._REPO_ROOT", str(tmp_path))
        monkeypatch.delenv("SAMPLES_FILE", raising=False)
        d = tmp_path / "samples"
        d.mkdir()
        (d / "index.json").write_text('[{"title":"Test"}]')
        from app.main import _load_samples
        assert _load_samples() == [{"title": "Test"}]

    def test_absolute_path_used_directly(self, monkeypatch, tmp_path):
        f = tmp_path / "custom.json"
        f.write_text('[{"title":"Custom"}]')
        monkeypatch.setenv("SAMPLES_FILE", str(f))
        from app.main import _load_samples
        assert _load_samples() == [{"title": "Custom"}]

    def test_missing_file_returns_empty(self, monkeypatch):
        monkeypatch.setenv("SAMPLES_FILE", "/no/such/file.json")
        from app.main import _load_samples
        assert _load_samples() == []


# ── UTF-8 access code ─────────────────────────────────────────────────────────


class TestUTF8AccessCode:
    def test_non_ascii_code_no_type_error(self, monkeypatch):
        """Non-ASCII str in compare_digest raises TypeError; UTF-8 encoding prevents it."""
        import hmac as hmac_mod
        with pytest.raises(TypeError):
            hmac_mod.compare_digest("café", "valid_code")
        monkeypatch.setenv("ACCESS_CODES", "a:valid_code:5")
        am = _make_access()
        assert am.check_code("café") is None

    def test_non_ascii_unit_check_code(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "a:valid:5")
        am = _make_access()
        assert am.check_code("éè") is None

    def test_correct_code_still_works(self, monkeypatch):
        monkeypatch.setenv("ACCESS_CODES", "alice:mycode:5")
        am = _make_access()
        assert am.check_code("mycode") == "alice"

    def test_all_codes_compared_with_bytes(self, monkeypatch):
        import hmac as hmac_mod
        monkeypatch.setenv("ACCESS_CODES", "a:ca:5,b:cb:5,c:cc:5")
        am = _make_access()
        calls = []
        orig = hmac_mod.compare_digest

        def track(a, b):
            calls.append(1)
            return orig(a, b)

        monkeypatch.setattr(hmac_mod, "compare_digest", track)
        am.check_code("cb")
        assert len(calls) == 3
