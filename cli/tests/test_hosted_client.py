"""Tests for hosted_client.py. No real network; httpx.get/post are patched."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

import hosted_client


def make_response(status_code: int, body) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if isinstance(body, dict) or isinstance(body, list):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = Exception("not JSON")
        resp.text = body
    return resp


URL = "http://localhost:8000"
HOSTED_URL = "https://api.example.com"


# ── access code ──────────────────────────────────────────────────────────────

class TestAccessCode:
    def test_flag_wins(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_ACCESS_CODE", "env-code")
        assert hosted_client.resolve_access_code("flag-code") == "flag-code"

    def test_env_used_when_no_flag(self, monkeypatch):
        monkeypatch.setenv("SYSTEMIQ_ACCESS_CODE", "env-code")
        assert hosted_client.resolve_access_code(None) == "env-code"

    def test_none_when_neither(self, monkeypatch):
        monkeypatch.delenv("SYSTEMIQ_ACCESS_CODE", raising=False)
        assert hosted_client.resolve_access_code(None) is None

    def test_require_missing_exits_1(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            hosted_client.require_access_code(None)
        assert exc_info.value.code == 1
        assert "access code is required" in capsys.readouterr().err

    def test_require_present_returns_it(self):
        assert hosted_client.require_access_code("mycode") == "mycode"

    def test_code_never_printed_on_error(self, capsys):
        """A secret access code must never appear in stdout/stderr, even in error paths."""
        secret = "super-secret-access-code-123"
        with patch("hosted_client.httpx.post", return_value=make_response(403, {"detail": "nope"})):
            with pytest.raises(SystemExit):
                hosted_client.submit_job(URL, secret, "idea text")
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err


# ── mode detection / wake-up ──────────────────────────────────────────────────

class TestDetectMode:
    def test_reachable_hosted(self):
        with patch("hosted_client.httpx.get", return_value=make_response(200, {"hosted": True, "max_idea_chars": 2000})):
            result = hosted_client.detect_mode(HOSTED_URL)
        assert result["hosted"] is True

    def test_reachable_not_hosted(self):
        with patch("hosted_client.httpx.get", return_value=make_response(200, {"hosted": False, "max_idea_chars": 20000})):
            result = hosted_client.detect_mode(URL)
        assert result["hosted"] is False

    def test_localhost_unreachable_prints_today_message(self, capsys):
        with patch("hosted_client.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.detect_mode(URL)
        assert exc_info.value.code == 1
        assert "backend not running" in capsys.readouterr().err

    def test_non_localhost_wakes_up_then_succeeds(self, capsys):
        attempts = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            make_response(200, {"hosted": True, "max_idea_chars": 2000}),
        ]

        def fake_get(url, *args, **kwargs):
            result = attempts.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        sleeps = []
        with patch("hosted_client.httpx.get", side_effect=fake_get):
            result = hosted_client.detect_mode(HOSTED_URL, sleep=sleeps.append)

        assert result["hosted"] is True
        assert sleeps == [hosted_client.WAKE_POLL_SECONDS, hosted_client.WAKE_POLL_SECONDS]
        assert "waking up" in capsys.readouterr().err.lower()

    def test_non_localhost_gives_up_after_wake_timeout(self, capsys):
        sleeps = []
        with patch("hosted_client.httpx.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.detect_mode(HOSTED_URL, sleep=sleeps.append)

        assert exc_info.value.code == 1
        n_expected = hosted_client.WAKE_TIMEOUT_SECONDS // hosted_client.WAKE_POLL_SECONDS
        assert len(sleeps) == n_expected
        err = capsys.readouterr().err
        assert "Server unavailable" in err
        assert hosted_client.SAMPLES_PAGE_URL in err


# ── idea length ───────────────────────────────────────────────────────────────

class TestIdeaLength:
    def test_within_limit_ok(self):
        hosted_client.check_idea_length("short idea", 100)  # must not raise

    def test_over_limit_exits(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            hosted_client.check_idea_length("x" * 101, 100)
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "too long" in err
        assert "100" in err


# ── privacy notice / confirmation ────────────────────────────────────────────

class TestConfirmHostedRun:
    def test_yes_flag_skips_prompt(self, capsys):
        hosted_client.confirm_hosted_run(yes=True)
        err = capsys.readouterr().err
        assert "Before you send" in err
        assert hosted_client.GROQ_RETENTION_LINE in err

    def test_notice_contains_exact_groq_retention_line(self, capsys):
        hosted_client.confirm_hosted_run(yes=True)
        err = capsys.readouterr().err
        assert "Groq: zero data retention is enabled in the account settings for this demo." in err

    def test_notice_always_printed_even_on_prompt(self, capsys):
        hosted_client.confirm_hosted_run(yes=False, isatty=True, input_func=lambda prompt: "y")
        assert "Before you send" in capsys.readouterr().err

    def test_answer_y_continues(self):
        hosted_client.confirm_hosted_run(yes=False, isatty=True, input_func=lambda prompt: "y")  # must not raise

    def test_answer_yes_continues(self):
        hosted_client.confirm_hosted_run(yes=False, isatty=True, input_func=lambda prompt: "YES")  # must not raise

    def test_answer_n_aborts(self):
        with pytest.raises(SystemExit) as exc_info:
            hosted_client.confirm_hosted_run(yes=False, isatty=True, input_func=lambda prompt: "n")
        assert exc_info.value.code == 1

    def test_answer_empty_aborts(self):
        with pytest.raises(SystemExit) as exc_info:
            hosted_client.confirm_hosted_run(yes=False, isatty=True, input_func=lambda prompt: "")
        assert exc_info.value.code == 1

    def test_non_tty_without_yes_refuses(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            hosted_client.confirm_hosted_run(yes=False, isatty=False)
        assert exc_info.value.code == 1
        assert "--yes" in capsys.readouterr().err


# ── job submission ────────────────────────────────────────────────────────────

class TestSubmitJob:
    def test_202_returns_job_info(self):
        with patch(
            "hosted_client.httpx.post",
            return_value=make_response(202, {"job_id": "abc123", "status": "queued", "position": 1}),
        ) as mock_post:
            result = hosted_client.submit_job(URL, "mycode", "an idea")
        assert result == {"job_id": "abc123", "status": "queued", "position": 1}
        assert mock_post.call_args.kwargs["headers"]["X-Access-Code"] == "mycode"
        assert mock_post.call_args.kwargs["json"] == {"idea": "an idea"}

    def test_sample_response_exits_3(self, capsys):
        body = {
            "status": "sample", "sample": True, "reason": "capacity",
            "samples": [{"title": "Clinic app", "url": "http://example.com/s1.md"}],
        }
        with patch("hosted_client.httpx.post", return_value=make_response(200, body)):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.submit_job(URL, "mycode", "an idea")
        assert exc_info.value.code == 3
        out = capsys.readouterr().out
        assert "capacity" in out
        assert "Clinic app" in out
        assert "No design was generated." in out

    @pytest.mark.parametrize("status", [403, 422, 429, 503])
    def test_error_statuses_without_detail(self, status, capsys):
        with patch("hosted_client.httpx.post", return_value=make_response(status, {})):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.submit_job(URL, "mycode", "an idea")
        assert exc_info.value.code == 1
        assert capsys.readouterr().err.startswith("error:")

    def test_detail_preferred_over_fallback(self, capsys):
        with patch("hosted_client.httpx.post", return_value=make_response(403, {"detail": "bad code"})):
            with pytest.raises(SystemExit):
                hosted_client.submit_job(URL, "mycode", "an idea")
        assert "bad code" in capsys.readouterr().err

    def test_other_status_falls_back(self, capsys):
        with patch("hosted_client.httpx.post", return_value=make_response(500, {})):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.submit_job(URL, "mycode", "an idea")
        assert exc_info.value.code == 1
        assert "500" in capsys.readouterr().err

    def test_connect_error(self, capsys):
        with patch("hosted_client.httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.submit_job(URL, "mycode", "an idea")
        assert exc_info.value.code == 1


# ── job polling ───────────────────────────────────────────────────────────────

class TestPollJob:
    def test_queued_then_running_then_done(self, capsys):
        responses = [
            make_response(200, {"status": "queued", "stage": None, "detail": None, "position": 2, "error": None}),
            make_response(200, {"status": "running", "stage": "extracting", "detail": None, "position": None, "error": None}),
            make_response(200, {"status": "running", "stage": "writing", "detail": {"group": 2, "of": 4}, "position": None, "error": None}),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": {"stage": "validated"}}),
        ]
        with patch("hosted_client.httpx.get", side_effect=responses):
            result = hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)

        assert result == {"stage": "validated"}
        out = capsys.readouterr().out
        assert "Queued (position 2)" in out
        assert "Extracting requirements" in out
        assert "Writing design (2/4)" in out
        assert "Done" in out

    def test_duplicate_state_not_reprinted(self, capsys):
        responses = [
            make_response(200, {"status": "queued", "stage": None, "detail": None, "position": 1, "error": None}),
            make_response(200, {"status": "queued", "stage": None, "detail": None, "position": 1, "error": None}),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": {}}),
        ]
        with patch("hosted_client.httpx.get", side_effect=responses):
            hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)
        out = capsys.readouterr().out
        assert out.count("Queued (position 1)") == 1

    def test_failed_job_prints_message_and_exits_1(self, capsys):
        responses = [
            make_response(200, {"status": "failed", "stage": None, "detail": None, "position": None, "error": {"message": "backend exploded"}}),
        ]
        with patch("hosted_client.httpx.get", side_effect=responses):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)
        assert exc_info.value.code == 1
        assert "backend exploded" in capsys.readouterr().err

    def test_404_expired(self, capsys):
        with patch("hosted_client.httpx.get", return_value=make_response(404, {})):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)
        assert exc_info.value.code == 1
        assert "expired" in capsys.readouterr().err

    def test_timeout(self, capsys):
        clock_vals = iter([0, 0, hosted_client.JOB_TIMEOUT_SECONDS + 1])

        def fake_clock():
            return next(clock_vals)

        with patch(
            "hosted_client.httpx.get",
            return_value=make_response(200, {"status": "queued", "stage": None, "detail": None, "position": 1, "error": None}),
        ):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.poll_job(URL, "job1", clock=fake_clock, sleep=lambda s: None)
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Still running" in err
        assert "--job job1" in err

    def test_three_transient_errors_in_a_row_exit_1(self, capsys):
        with patch("hosted_client.httpx.get", side_effect=httpx.ConnectError("blip")):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)
        assert exc_info.value.code == 1
        assert "lost contact" in capsys.readouterr().err

    def test_transient_error_recovers_before_three(self, capsys):
        responses = [
            httpx.ConnectError("blip"),
            httpx.ConnectError("blip"),
            make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": {"ok": True}}),
        ]

        def fake_get(url, *args, **kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("hosted_client.httpx.get", side_effect=fake_get):
            result = hosted_client.poll_job(URL, "job1", clock=_fake_clock(), sleep=lambda s: None)
        assert result == {"ok": True}


def _fake_clock():
    """A monotonically increasing fake clock, starting at 0, for poll_job tests."""
    state = {"t": 0}

    def _clock():
        state["t"] += 1
        return state["t"]

    return _clock


# ── samples ───────────────────────────────────────────────────────────────────

class TestBlobUrlToRaw:
    def test_converts_blob_url(self):
        url = "https://github.com/TFD666/system-iq/blob/main/samples/clinic.md"
        assert hosted_client.blob_url_to_raw(url) == (
            "https://raw.githubusercontent.com/TFD666/system-iq/main/samples/clinic.md"
        )

    def test_heals_backslashes_before_converting(self):
        """A url saved from a Windows --out path may still contain backslashes;
        blob_url_to_raw must normalize them defensively before matching."""
        url = "https://github.com/TFD666/system-iq/blob/main/samples\\clinic.md"
        assert hosted_client.blob_url_to_raw(url) == (
            "https://raw.githubusercontent.com/TFD666/system-iq/main/samples/clinic.md"
        )


class TestFetchSample:
    INDEX = [
        {"title": "Clinic app", "url": "https://github.com/TFD666/system-iq/blob/main/samples/clinic.md"},
        {"title": "Todo app", "url": "https://github.com/TFD666/system-iq/blob/main/samples/todo.md"},
    ]

    def test_success_writes_file(self, tmp_path, capsys):
        out_path = str(tmp_path / "out.md")
        responses = [make_response(200, self.INDEX), make_response(200, "## Clinic design\n")]
        with patch("hosted_client.httpx.get", side_effect=responses):
            hosted_client.fetch_sample(1, out_path, force=False)
        assert (tmp_path / "out.md").read_text() == "## Clinic design\n"

    def test_default_out_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        responses = [make_response(200, self.INDEX), make_response(200, "## Clinic design\n")]
        with patch("hosted_client.httpx.get", side_effect=responses):
            hosted_client.fetch_sample(1, None, force=False)
        assert (tmp_path / "system-design.SAMPLE.md").exists()

    def test_empty_index(self, capsys):
        with patch("hosted_client.httpx.get", return_value=make_response(200, [])):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.fetch_sample(1, None, force=False)
        assert exc_info.value.code == 1
        assert "No sample 1 is published" in capsys.readouterr().err

    def test_missing_entry_n_too_high(self, capsys):
        with patch("hosted_client.httpx.get", return_value=make_response(200, self.INDEX)):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.fetch_sample(3, None, force=False)
        assert exc_info.value.code == 1
        assert "No sample 3 is published" in capsys.readouterr().err

    def test_overwrite_refused_without_force(self, tmp_path, capsys):
        out_path = tmp_path / "out.md"
        out_path.write_text("existing")
        with patch("hosted_client.httpx.get", return_value=make_response(200, self.INDEX)):
            with pytest.raises(SystemExit) as exc_info:
                hosted_client.fetch_sample(1, str(out_path), force=False)
        assert exc_info.value.code == 1
        assert "already exists" in capsys.readouterr().err
        assert out_path.read_text() == "existing"

    def test_overwrite_allowed_with_force(self, tmp_path):
        out_path = tmp_path / "out.md"
        out_path.write_text("existing")
        responses = [make_response(200, self.INDEX), make_response(200, "## New design\n")]
        with patch("hosted_client.httpx.get", side_effect=responses):
            hosted_client.fetch_sample(1, str(out_path), force=True)
        assert out_path.read_text() == "## New design\n"
