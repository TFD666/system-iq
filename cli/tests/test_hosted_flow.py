"""Integration tests for systemiq.py's hosted (job-mode) flow via main()."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from systemiq import main


def make_response(status_code: int, body) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if isinstance(body, (dict, list)):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = Exception("not JSON")
        resp.text = body
    return resp


HOSTED_URL = "https://api.example.com"
DONE_RESULT = {
    "stage": "validated",
    "requirements": {
        "project_summary": "A to-do app", "app_type": "web", "core_features": [],
        "user_roles": [], "expected_scale": {"users": None, "peak_requests_per_second": None, "data_volume": None},
        "realtime": None, "geospatial": None, "authentication": None, "search_filtering": None,
        "media_storage": None, "payments": None, "offline_support": None,
        "external_integrations": [], "constraints": [], "assumptions": [], "unknowns": [],
    },
    "decisions": [],
    "meta": {"decision_model": "jev-1.13-free", "input_tokens": 1, "output_tokens": 1, "validation_status": "passed"},
    "design_markdown": "## 1. Architecture overview\n\nSome text.",
    "design_warnings": [],
    "validation": [],
    "revisions": [],
}


def _healthz(hosted, max_idea_chars=2000):
    return make_response(200, {"status": "ok", "hosted": hosted, "max_idea_chars": max_idea_chars})


# ── mode detection picks the right branch ────────────────────────────────────

class TestModeDetectionBranching:
    def test_hosted_server_uses_job_flow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        get_responses = [_healthz(True), make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT})]
        post_responses = [make_response(202, {"job_id": "job1", "status": "queued", "position": 1})]

        with patch("hosted_client.httpx.get", side_effect=get_responses), \
             patch("hosted_client.httpx.post", side_effect=post_responses), \
             patch("hosted_client.time.sleep"), \
             patch("sys.argv", ["systemiq", "Build a to-do app", "--access-code", "mycode", "--yes"]):
            main()

        assert (tmp_path / "system-design.md").exists()

    def test_non_hosted_server_uses_local_flow(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("hosted_client.httpx.get", return_value=_healthz(False)), \
             patch("systemiq.httpx.post", return_value=make_response(200, DONE_RESULT)), \
             patch("sys.argv", ["systemiq", "Build a to-do app", "--access-code", "mycode", "--yes"]):
            main()
        assert (tmp_path / "system-design.md").exists()


# ── access code ──────────────────────────────────────────────────────────────

class TestAccessCodeGate:
    def test_missing_code_exits_before_any_post(self, capsys):
        def fail_post(*args, **kwargs):
            raise AssertionError("must not POST /jobs without an access code")

        with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
             patch("hosted_client.httpx.post", side_effect=fail_post), \
             patch("sys.argv", ["systemiq", "Build a to-do app"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "access code is required" in capsys.readouterr().err

    def test_code_from_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})) as mock_post, \
             patch("hosted_client.httpx.get") as mock_get_poll, \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "flagcode", "--yes"]):
            mock_get_poll.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()
        assert mock_post.call_args.kwargs["headers"]["X-Access-Code"] == "flagcode"

    def test_code_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SYSTEMIQ_ACCESS_CODE", "envcode")
        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})) as mock_post, \
             patch("sys.argv", ["systemiq", "idea", "--yes"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()
        assert mock_post.call_args.kwargs["headers"]["X-Access-Code"] == "envcode"

    def test_code_never_in_stdout_or_stderr(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        secret = "top-secret-code-xyz"
        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(403, {"detail": "bad code"})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", secret, "--yes"]):
            mock_get.return_value = _healthz(True)
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err


# ── idea length ───────────────────────────────────────────────────────────────

def test_idea_too_long_for_hosted(capsys):
    with patch("hosted_client.httpx.get", return_value=_healthz(True, max_idea_chars=10)), \
         patch("sys.argv", ["systemiq", "this idea is definitely too long", "--access-code", "c", "--yes"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "too long" in err
    assert "10" in err


# ── privacy notice / confirmation prompt ─────────────────────────────────────

class TestConfirmPrompt:
    def test_yes_flag_skips_prompt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()  # must not block on input()

    def test_non_tty_without_yes_refuses(self, capsys):
        with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
             patch("sys.stdin.isatty", return_value=False), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "--yes" in capsys.readouterr().err

    def test_prompt_n_aborts(self, capsys):
        with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="n"), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_prompt_y_continues(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="y"), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()


# ── dry-run ───────────────────────────────────────────────────────────────────

class TestHostedDryRun:
    def test_contacts_nothing(self, capsys):
        def fail(*args, **kwargs):
            raise AssertionError("dry-run must not contact the server at all")

        with patch("hosted_client.httpx.get", side_effect=fail), \
             patch("hosted_client.httpx.post", side_effect=fail), \
             patch("systemiq.httpx.post", side_effect=fail), \
             patch("sys.argv", ["systemiq", "Build a to-do app", "--access-code", "c", "--dry-run"]):
            main()

        out = capsys.readouterr()
        assert "/jobs" in out.out
        assert "characters" in out.out
        assert "Before you send" in out.err

    def test_exits_0(self):
        with patch("hosted_client.httpx.get", side_effect=AssertionError("no network")), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--dry-run"]):
            main()  # no SystemExit raised -> implicit 0

    def test_without_access_code_unchanged(self, capsys):
        # Existing local dry-run behavior: no access code -> no privacy notice.
        with patch("hosted_client.httpx.get", side_effect=AssertionError("no network")), \
             patch("sys.argv", ["systemiq", "idea", "--dry-run"]):
            main()
        err = capsys.readouterr().err
        assert "Before you send" not in err


# ── sample response (capacity / samples-mode) ────────────────────────────────

def test_sample_response_exits_3_and_prints_links(capsys):
    body = {
        "status": "sample", "sample": True, "reason": "capacity",
        "samples": [{"title": "Clinic app", "url": "http://example.com/s1.md"}],
    }
    with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
         patch("hosted_client.httpx.post", return_value=make_response(200, body)), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 3
    out = capsys.readouterr().out
    assert "Clinic app" in out
    assert "No design was generated." in out


# ── error statuses from /jobs ────────────────────────────────────────────────

@pytest.mark.parametrize("status", [403, 422, 429, 503])
def test_jobs_error_statuses_exit_1(status, capsys):
    with patch("hosted_client.httpx.get", return_value=_healthz(True)), \
         patch("hosted_client.httpx.post", return_value=make_response(status, {"detail": "a reason"})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert "a reason" in capsys.readouterr().err


# ── job failure / 404 / fallback / skipped notes ─────────────────────────────

def test_failed_job_exits_1(capsys):
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        mock_get.side_effect = [
            _healthz(True),
            make_response(200, {"status": "failed", "stage": None, "detail": None, "position": None, "error": {"message": "boom"}}),
        ]
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert "boom" in capsys.readouterr().err


def test_404_during_poll_exits_1(capsys):
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        mock_get.side_effect = [_healthz(True), make_response(404, {})]
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert "expired" in capsys.readouterr().err


def test_fallback_note_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = json.loads(json.dumps(DONE_RESULT))
    result["meta"]["fallback"] = "llm_only (Jev quota exhausted)"
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        mock_get.side_effect = [
            _healthz(True),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": result}),
        ]
        main()
    err = capsys.readouterr().err
    assert "llm_only (Jev quota exhausted)" in err


def test_validation_skipped_note_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = json.loads(json.dumps(DONE_RESULT))
    result["meta"]["validation_status"] = "skipped"
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
        mock_get.side_effect = [
            _healthz(True),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": result}),
        ]
        main()
    assert "validation was skipped" in capsys.readouterr().err


# ── file written with header, overwrite refusal ──────────────────────────────

def test_job_done_writes_file_with_header_and_refuses_overwrite(tmp_path, capsys):
    out_path = tmp_path / "out.md"
    out_path.write_text("existing")
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--out", str(out_path)]):
        mock_get.side_effect = [
            _healthz(True),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
        ]
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert out_path.read_text() == "existing"


def test_job_done_writes_file_with_force(tmp_path):
    out_path = tmp_path / "out.md"
    out_path.write_text("existing")
    with patch("hosted_client.httpx.get") as mock_get, \
         patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
         patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--out", str(out_path), "--force"]):
        mock_get.side_effect = [
            _healthz(True),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
        ]
        main()
    content = out_path.read_text()
    assert "Generated by System IQ" in content
    assert "## 1. Architecture overview" in content


# ── --job ─────────────────────────────────────────────────────────────────────

class TestJobFlag:
    def test_resumes_polling_no_code_no_prompt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def fail_input(*args, **kwargs):
            raise AssertionError("--job must not prompt")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("builtins.input", side_effect=fail_input), \
             patch("sys.argv", ["systemiq", "--job", "job1"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()
        assert (tmp_path / "system-design.md").exists()

    def test_needs_hosted_server(self, capsys):
        with patch("hosted_client.httpx.get", return_value=_healthz(False)), \
             patch("sys.argv", ["systemiq", "--job", "job1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "--job needs a hosted server" in capsys.readouterr().err


# ── --sample ──────────────────────────────────────────────────────────────────

class TestSampleFlag:
    def test_success_no_server_contact_for_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        index = [{"title": "Clinic app", "url": "https://github.com/TFD666/system-iq/blob/main/samples/clinic.md"}]
        with patch("hosted_client.httpx.get") as mock_get, \
             patch("sys.argv", ["systemiq", "--sample", "1"]):
            mock_get.side_effect = [make_response(200, index), make_response(200, "## Clinic design\n")]
            main()
        assert (tmp_path / "system-design.SAMPLE.md").read_text() == "## Clinic design\n"

    def test_empty_index_exits_1(self, capsys):
        with patch("hosted_client.httpx.get", return_value=make_response(200, [])), \
             patch("sys.argv", ["systemiq", "--sample", "1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "No sample 1 is published" in capsys.readouterr().err

    def test_overwrite_refused_without_force(self, tmp_path, capsys):
        out_path = tmp_path / "s.md"
        out_path.write_text("existing")
        index = [{"title": "Clinic app", "url": "https://github.com/TFD666/system-iq/blob/main/samples/clinic.md"}]
        with patch("hosted_client.httpx.get", return_value=make_response(200, index)), \
             patch("sys.argv", ["systemiq", "--sample", "1", "--out", str(out_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert out_path.read_text() == "existing"
