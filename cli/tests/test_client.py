"""
Tests for the backend-calling logic in systemiq.py.
httpx.post is mocked throughout — no real network calls.
"""
import json
import sys
from unittest.mock import MagicMock, patch

import httpx
import pytest

# conftest.py already adds cli/ to sys.path, so this import works
from systemiq import send_to_backend


# ── runtime token builder ──────────────────────────────────────────────────────
# Assembled at runtime so no complete credential literal appears in source text,
# avoiding GitHub secret-scanning alerts.

def _sk_key():
    """Return an OpenAI-style secret key built from short fragments."""
    return "sk-" + "abcdefghijklmnop" + "qrstuvwxyz1234"


# ── helpers ────────────────────────────────────────────────────────────────────

def make_response(status_code: int, body) -> MagicMock:
    """
    Build a mock httpx.Response.
    body can be a dict (serialised to JSON) or a plain string.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code

    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = Exception("not JSON")
        resp.text = body

    return resp


DUMMY_URL = "http://localhost:8000"
DUMMY_TEXT = "Build a to-do app"

# A minimal success payload the backend would return
SUCCESS_BODY = {
    "stage": "extracted",
    "requirements": {
        "project_summary": "A to-do app",
        "app_type": "web",
        "core_features": ["tasks"],
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
    },
}


# ── success case ───────────────────────────────────────────────────────────────

def test_200_success_prints_json(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    out = capsys.readouterr().out
    # Output must be valid JSON and contain the stage field
    parsed = json.loads(out)
    assert parsed["stage"] == "extracted"


# ── connection / transport errors ──────────────────────────────────────────────

def test_connection_refused_prints_error_and_exits(capsys):
    with patch("systemiq.httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "backend not running" in err


def test_timeout_prints_error_and_exits(capsys):
    with patch("systemiq.httpx.post", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "timed out" in err


# ── HTTP error status codes ────────────────────────────────────────────────────

def test_429_prints_rate_limit_error_and_exits(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(429, {"detail": "too many"})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "rate limited" in err


def test_502_prints_extraction_error_and_exits(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(502, {"detail": "bad"})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "extract" in err


def test_504_prints_timeout_error_and_exits(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(504, {"detail": "timeout"})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "timed out" in err


def test_other_non_200_prints_status_code_and_exits(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(503, {"detail": "unavailable"})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    # Must include the numeric status code
    assert "503" in err


def test_non_json_body_prints_unexpected_error_and_exits(capsys):
    # Status 200 but body is not JSON
    with patch("systemiq.httpx.post", return_value=make_response(200, "not json at all")):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "unexpected" in err


# ── dry-run ────────────────────────────────────────────────────────────────────

def test_dry_run_makes_no_network_call(capsys):
    """
    --dry-run is tested via main() because that is where the flag is parsed.
    We patch httpx.post to a side-effect that fails if called, proving
    no network call is made.

    The input contains a fake API key so we can also verify that the preview
    shows [REDACTED:...] rather than the raw secret value.
    """
    from systemiq import main

    # A fake key long enough to match the api_key pattern — built at runtime
    # so no complete credential literal appears in source text.
    fake_key = _sk_key()
    idea_with_secret = f"Build a to-do app. Key: {fake_key}"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post must not be called during --dry-run")

    with patch("systemiq.httpx.post", side_effect=fail_if_called):
        with patch("sys.argv", ["systemiq", idea_with_secret, "--dry-run"]):
            main()  # must not raise

    out = capsys.readouterr().out
    # Output must mention the URL and a character count
    assert "/design" in out
    assert "characters" in out
    # The raw secret value must NOT appear in stdout (the preview is redacted)
    assert fake_key not in out
    # The REDACTED token must appear in the preview instead
    assert "[REDACTED:" in out



# ── redaction integration tests ────────────────────────────────────────────────

def test_secrets_are_not_in_outgoing_payload(capsys):
    """
    When the input contains a fake API key and a fake email, the payload
    sent to httpx.post must not contain those values.
    """
    from systemiq import main

    fake_key = _sk_key()
    fake_idea = fake_key + " and alice@example.com"
    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", fake_idea]):
            main()

    sent_idea = captured_payload.get("idea", "")
    assert fake_key not in sent_idea
    assert "alice@example.com" not in sent_idea
    assert "[REDACTED:" in sent_idea


def test_no_redact_sends_original_and_warns(capsys):
    """
    --no-redact must send the text as-is and print a warning to stderr.
    """
    from systemiq import main

    fake_idea = "alice@example.com"
    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", fake_idea, "--no-redact"]):
            main()

    # The original email must reach the backend unchanged
    assert captured_payload.get("idea") == "alice@example.com"
    err = capsys.readouterr().err
    assert "warning" in err
    assert "no-redact" in err
