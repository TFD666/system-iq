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
#
# send_to_backend now prints a human-readable rendering by default (the raw
# JSON dump moved behind --json / json_mode=True), so the old assertion that
# stdout IS the JSON body no longer holds for the default call. Split into a
# readable-mode test and an explicit --json test below.

def test_200_success_prints_readable_requirements(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    out = capsys.readouterr().out
    assert "Requirements:" in out
    assert "app type: web" in out
    assert "A to-do app" in out


def test_json_flag_prints_valid_raw_json_only(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, json_mode=True)

    out = capsys.readouterr().out
    # Output must be valid JSON and contain the stage field; nothing else on stdout.
    parsed = json.loads(out)
    assert parsed["stage"] == "extracted"


# ── readable rendering (requirements + decisions + meta) ───────────────────────

FULL_SUCCESS_BODY = {
    "stage": "decided",
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
        "unknowns": ["payments not specified"],
        "evidence": {"authentication": "must log in with a password"},
    },
    "decisions": [
        {
            "id": "primary_database",
            "question": "Which database best suits the data storage needs of this project?",
            "status": "accepted",
            "choice": "PostgreSQL",
            "probability": 0.82,
            "top_alternatives": [{"option": "PostgreSQL", "probability": 0.82}],
            "based_on_unknowns": False,
        },
        {
            "id": "cache_needed",
            "question": "Does this project need a caching layer to meet its performance requirements?",
            "status": "uncertain",
            "choice": None,
            "probability": 0.5,
            "top_alternatives": [],
            "based_on_unknowns": True,
        },
    ],
    "meta": {
        "decision_model": "jev-1.13-free",
        "input_tokens": 120,
        "output_tokens": 40,
        "decision_billing": "free",
        "decision_cost": 0.0,
    },
}


def test_readable_output_shows_decisions_table_and_summary(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, FULL_SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    out = capsys.readouterr().out
    assert "Decisions:" in out
    assert "primary_database" in out
    assert "PostgreSQL" in out
    assert "82%" in out
    assert "jev-1.13-free" in out
    assert "120" in out and "40" in out


def test_readable_output_shows_evidence_quote(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, FULL_SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    out = capsys.readouterr().out
    assert "authentication: yes" in out
    assert "must log in with a password" in out


def test_readable_output_marks_based_on_unknowns(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, FULL_SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    out = capsys.readouterr().out
    table_lines = [
        line for line in out.splitlines()
        if line.strip().startswith("cache_needed")
    ]
    assert table_lines, "expected a decisions-table row for cache_needed"
    assert table_lines[0].rstrip().endswith("?")

    # The row for a decision that is NOT based on unknowns must not be marked.
    other_lines = [
        line for line in out.splitlines()
        if line.strip().startswith("primary_database")
    ]
    assert other_lines
    assert not other_lines[0].rstrip().endswith("?")


def test_fake_decision_model_prints_warning(capsys):
    fake_body = json.loads(json.dumps(FULL_SUCCESS_BODY))
    fake_body["meta"]["decision_model"] = "fake (demo only)"

    with patch("systemiq.httpx.post", return_value=make_response(200, fake_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "FAKE" in err


def test_non_free_billing_prints_warning(capsys):
    billed_body = json.loads(json.dumps(FULL_SUCCESS_BODY))
    billed_body["meta"]["decision_billing"] = "paid"
    billed_body["meta"]["decision_cost"] = 0.05

    with patch("systemiq.httpx.post", return_value=make_response(200, billed_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    err = capsys.readouterr().err
    assert "warning" in err
    assert "billed" in err


def test_readable_output_handles_missing_optional_fields(capsys):
    # Older-style response: no evidence, no question text, no meta at all.
    minimal_body = {
        "stage": "decided",
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
            "realtime": None,
            "geospatial": None,
            "authentication": True,
            "search_filtering": None,
            "media_storage": None,
            "payments": None,
            "offline_support": None,
            "external_integrations": [],
            "constraints": [],
            "assumptions": [],
            "unknowns": [],
        },
        "decisions": [
            {
                "id": "primary_database",
                "status": "accepted",
                "choice": "PostgreSQL",
                "probability": 0.82,
                "top_alternatives": [],
                "based_on_unknowns": False,
            }
        ],
    }

    with patch("systemiq.httpx.post", return_value=make_response(200, minimal_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)  # must not raise

    out = capsys.readouterr().out
    assert "Requirements:" in out
    assert "authentication: yes" in out
    assert "primary_database" in out


def test_readable_output_is_ascii_only(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, FULL_SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        stream.encode("ascii")  # raises UnicodeEncodeError if anything non-ASCII slipped in


# ── stage, design-file writing, header ──────────────────────────────────────────

DESIGNED_BODY = {
    "stage": "designed",
    "requirements": SUCCESS_BODY["requirements"],
    "decisions": FULL_SUCCESS_BODY["decisions"],
    "meta": {
        "decision_model": "jev-1.13-free",
        "input_tokens": 50,
        "output_tokens": 20,
        "decision_billing": "free",
        "decision_cost": 0.0,
        "llm_model": "qwen/qwen3-27b",
        "design_prompt_tokens": 400,
        "design_completion_tokens": 900,
        "design_group_stats": [
            {"id": "g1", "prompt_tokens": 100, "completion_tokens": 200, "retries": 0, "elapsed_seconds": 1.5},
            {"id": "g2", "prompt_tokens": 100, "completion_tokens": 250, "retries": 1, "elapsed_seconds": 3.0},
            {"id": "g3", "prompt_tokens": 100, "completion_tokens": 225, "retries": 0, "elapsed_seconds": 1.0},
            {"id": "g4", "prompt_tokens": 100, "completion_tokens": 225, "retries": 0, "elapsed_seconds": 1.0},
        ],
    },
    "design_markdown": "## 1. Architecture overview\n\nSome generated text.",
    "design_warnings": ["missing heading: ## 7. Caching"],
}


def test_designed_response_writes_file_with_header(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Generated by System IQ V1" in content
    assert "qwen/qwen3-27b" in content
    assert "jev-1.13-free" in content
    assert "provisional" in content
    assert "## 1. Architecture overview" in content

    out = capsys.readouterr().out
    assert str(out_path) in out


def test_designed_response_prints_group_stats_line(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    # 4 groups, 1 retry (from g2), 6.5s total, 400/900 tokens (matches meta).
    assert "design: 4 groups, 1 retries, 6.5 s, 400/900 tokens" in out


def test_designed_response_prints_warnings(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "design warnings:" in out
    assert "missing heading: ## 7. Caching" in out


def test_designed_response_refuses_to_overwrite_without_force(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    out_path.write_text("existing content", encoding="utf-8")

    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert out_path.read_text(encoding="utf-8") == "existing content"  # untouched


def test_designed_response_force_overwrites(tmp_path):
    out_path = tmp_path / "design.md"
    out_path.write_text("old content", encoding="utf-8")

    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path), force=True)

    content = out_path.read_text(encoding="utf-8")
    assert "old content" not in content
    assert "## 1. Architecture overview" in content


def test_designed_response_default_out_path(tmp_path, monkeypatch):
    # No --out given: must write to ./system-design.md (cwd-relative).
    monkeypatch.chdir(tmp_path)
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert (tmp_path / "system-design.md").exists()


def test_json_mode_still_writes_file_but_prints_raw_json_only(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, json_mode=True, out_path=str(out_path))

    assert out_path.exists()  # the file is still written even with --json
    out = capsys.readouterr().out
    parsed = json.loads(out)  # but stdout is ONLY the raw JSON
    assert parsed["stage"] == "designed"


def test_design_stage_prints_free_tier_wait_notice(tmp_path, monkeypatch, capsys):
    # Wording changed again, from "5 to 10 minutes" to "2 to 5 minutes",
    # once the retry/validation work made the design stage faster per call.
    monkeypatch.chdir(tmp_path)
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL)  # default stage="design"

    err = capsys.readouterr().err
    assert "2 to 5 minutes" in err


def test_non_design_stage_skips_free_tier_wait_notice(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, SUCCESS_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, stage="extract")

    err = capsys.readouterr().err
    assert "2 to 5 minutes" not in err


def test_replay_decision_model_prints_warning(capsys):
    replay_body = json.loads(json.dumps(FULL_SUCCESS_BODY))
    replay_body["meta"]["decision_model"] = "replay (saved Jev output, not a live call)"

    with patch("systemiq.httpx.post", return_value=make_response(200, replay_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, stage="decide")

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "REPLAYED" in err


def test_stage_flag_is_sent_to_backend_payload():
    from systemiq import main

    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", "Build a to-do app", "--stage", "extract"]):
            main()

    assert captured_payload.get("stage") == "extract"


# ── validate stage: table, revisions line, header, --no-validate ───────────────

VALIDATED_BODY = {
    "stage": "validated",
    "requirements": SUCCESS_BODY["requirements"],
    "decisions": FULL_SUCCESS_BODY["decisions"],
    "meta": {
        "decision_model": "jev-1.13-free",
        "input_tokens": 50,
        "output_tokens": 20,
        "decision_billing": "free",
        "decision_cost": 0.0,
        "llm_model": "qwen/qwen3-27b",
        "design_prompt_tokens": 400,
        "design_completion_tokens": 900,
        "design_group_stats": DESIGNED_BODY["meta"]["design_group_stats"],
        "validation_calls": 2,
        "validation_input_tokens": 30,
        "validation_output_tokens": 10,
        "validation_status": "flagged",
        "validation_model": "jev-1.13-free",
    },
    "design_markdown": "## 1. Architecture overview\n\nSome generated text.",
    "design_warnings": ["validation: val_contradiction"],
    "validation": [
        {"id": "val_auth", "text": "Does it?", "probability": 0.2, "status": "flagged", "sections": [6, 8]},
        {"id": "val_contradiction", "text": "Any contradiction?", "probability": 0.65, "status": "flagged", "sections": []},
    ],
    "revisions": [
        {"round": 1, "sections_revised": [6, 8], "flagged_ids": ["val_auth"]},
    ],
}


def test_validated_response_prints_validation_table(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "Validation:" in out
    assert "val_auth" in out
    assert "20%" in out
    assert "flagged" in out
    assert "6, 8" in out


def test_validated_response_prints_revisions_line(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "revised sections: 6, 8 in 1 round" in out


def test_validated_response_prints_validation_summary_line(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "validation: flagged, 2 Jev requests" in out


# Was decision_model: on the real /validate endpoint decision_model is
# always fixed to "n/a (validation only)", so the summary line must read
# validation_model (falling back to decision_model only if that's absent).
def test_validation_summary_line_says_fake_when_validation_model_is_fake(tmp_path, capsys):
    fake_body = json.loads(json.dumps(VALIDATED_BODY))
    fake_body["meta"]["validation_model"] = "fake (demo only)"
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, fake_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "validation: flagged (fake), 0 real Jev requests" in out


def test_validation_summary_line_says_replayed_when_validation_model_is_replay(tmp_path, capsys):
    replay_body = json.loads(json.dumps(VALIDATED_BODY))
    replay_body["meta"]["validation_model"] = "replay (saved Jev output, not a live call)"
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, replay_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "validation: flagged (replayed), 0 real Jev requests" in out


def test_validation_summary_line_falls_back_to_decision_model_if_validation_model_missing(tmp_path, capsys):
    fake_body = json.loads(json.dumps(VALIDATED_BODY))
    del fake_body["meta"]["validation_model"]
    fake_body["meta"]["decision_model"] = "fake (demo only)"
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, fake_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    assert "validation: flagged (fake), 0 real Jev requests" in out


def test_validation_summary_line_says_real_jev_requests_otherwise(tmp_path, capsys):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    out = capsys.readouterr().out
    # jev-1.13-free is neither fake nor replay -- must show the real count.
    assert "(fake)" not in out
    assert "(replayed)" not in out
    assert "validation: flagged, 2 Jev requests" in out


def test_validated_response_header_says_validated_by_jev(tmp_path):
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "validated by Jev: flagged" in content


def test_validated_response_header_says_validation_skipped_when_skipped(tmp_path):
    skipped_body = json.loads(json.dumps(VALIDATED_BODY))
    skipped_body["meta"]["validation_status"] = "skipped"
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, skipped_body)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "validation skipped" in content


def test_designed_response_header_has_no_validation_line(tmp_path):
    # stage="designed" (e.g. --no-validate): no validation ran at all, so
    # the header must not claim a validation status.
    out_path = tmp_path / "design.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, DESIGNED_BODY)):
        send_to_backend(DUMMY_TEXT, DUMMY_URL, out_path=str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "validated by Jev" not in content
    assert "validation skipped" not in content


def test_max_revisions_flag_is_sent_to_backend_payload():
    from systemiq import main

    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", "Build a to-do app", "--max-revisions", "2"]):
            main()

    assert captured_payload.get("max_revisions") == 2


def test_no_validate_flag_stops_at_design_stage():
    from systemiq import main

    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", "Build a to-do app", "--no-validate"]):
            main()

    assert captured_payload.get("stage") == "design"


def test_default_stage_is_validate():
    from systemiq import main

    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, SUCCESS_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", "Build a to-do app"]):
            main()

    assert captured_payload.get("stage") == "validate"
    assert captured_payload.get("max_revisions") == 1


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
#
# 429/502/503/504 now prefer the backend's own "detail" string (see
# send_to_backend) over the old fixed message. The three tests below used to
# send a "detail" body and assert on the OLD fixed wording; that assumption
# is gone now that detail is shown, so they're rewritten to cover the
# fallback path (no usable detail) instead, and new tests below cover the
# detail-shown path for all four codes.

def test_429_falls_back_to_fixed_message_without_detail(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(429, {})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "rate limited" in err


def test_502_falls_back_to_fixed_message_without_detail(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(502, {})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "extract" in err


def test_504_falls_back_to_fixed_message_without_detail(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(504, {})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "timed out" in err


def test_503_falls_back_to_fixed_message_without_detail(capsys):
    # 503 previously had no dedicated handling at all (it fell through to the
    # generic "other" branch); it is now one of the four detail-aware codes.
    with patch("systemiq.httpx.post", return_value=make_response(503, {})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "misconfigured" in err


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_detail_aware_status_codes_print_backend_detail(capsys, status):
    # stage="decide": the default stage="design" now also prints a
    # free-tier wait-time notice to stderr, which would break this exact
    # match on err -- pick a stage that doesn't print that notice instead.
    with patch(
        "systemiq.httpx.post",
        return_value=make_response(status, {"detail": "a specific backend reason"}),
    ):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL, stage="decide")

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.strip() == "error: a specific backend reason"


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_detail_aware_status_codes_fall_back_on_non_json_body(capsys, status):
    # Same reason as above: avoid the design-stage notice line on stderr.
    with patch("systemiq.httpx.post", return_value=make_response(status, "not json")):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL, stage="decide")

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    # Falls back to the fixed message rather than crashing on bad JSON.
    assert err.strip().startswith("error:")


def test_other_non_200_prints_status_code_and_exits(capsys):
    # 500 is not one of the four detail-aware codes, so the old generic
    # "HTTP <code>: <detail>" format still applies, unchanged.
    with patch("systemiq.httpx.post", return_value=make_response(500, {"detail": "unavailable"})):
        with pytest.raises(SystemExit) as exc_info:
            send_to_backend(DUMMY_TEXT, DUMMY_URL)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    # Must include the numeric status code
    assert "500" in err


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


# ── --validate-saved / --design-file / --revise ─────────────────────────────────

from systemiq import load_design_file, load_validate_saved, send_validate_to_backend  # noqa: E402

VALIDATE_RESPONSE_BODY = {
    "stage": "validated",
    "requirements": SUCCESS_BODY["requirements"],
    "decisions": FULL_SUCCESS_BODY["decisions"],
    "meta": {
        "decision_model": "n/a (validation only)",
        "input_tokens": 0,
        "output_tokens": 0,
        "validation_calls": 1,
        "validation_input_tokens": 10,
        "validation_output_tokens": 5,
        "validation_status": "passed",
        "validation_model": "jev-1.13-free",
    },
    "design_markdown": "## 1. Architecture overview\n\nSome design text.",
    "design_warnings": [],
    "validation": [
        {"id": "val_auth", "text": "Does it?", "probability": 0.9, "status": "ok", "sections": [6]},
    ],
    "revisions": [],
}

_SAVED_RESPONSE_JSON = json.dumps({
    "requirements": SUCCESS_BODY["requirements"],
    "decisions": FULL_SUCCESS_BODY["decisions"],
    "design_markdown": "## 1. Architecture overview\n\nOriginal design text.",
})


def test_load_validate_saved_reads_a_bom_file(tmp_path):
    path = tmp_path / "saved.json"
    path.write_bytes(b"\xef\xbb\xbf" + _SAVED_RESPONSE_JSON.encode("utf-8"))

    requirements, decisions, design_markdown = load_validate_saved(str(path))
    assert requirements["app_type"] == SUCCESS_BODY["requirements"]["app_type"]
    assert decisions == FULL_SUCCESS_BODY["decisions"]
    assert "Original design text" in design_markdown


def test_load_validate_saved_missing_field_gives_a_clear_error(tmp_path):
    path = tmp_path / "saved.json"
    path.write_text(json.dumps({"requirements": SUCCESS_BODY["requirements"]}), encoding="utf-8")

    with pytest.raises(ValueError, match="design_markdown"):
        load_validate_saved(str(path))


def test_load_design_file_reads_a_bom_file(tmp_path):
    path = tmp_path / "design.md"
    path.write_bytes(b"\xef\xbb\xbf## 1. Heading\n\nEdited text.")

    text = load_design_file(str(path))
    assert text == "## 1. Heading\n\nEdited text."


def test_send_validate_to_backend_prints_notice_and_table(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATE_RESPONSE_BODY)) as mock_post:
        send_validate_to_backend(
            SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
            "## 1. Architecture overview\n\nSome text.", DUMMY_URL,
        )

    captured = capsys.readouterr()
    assert "validation only" in captured.err
    assert "no Groq call" in captured.err
    out = captured.out
    assert "Validation:" in out
    assert "val_auth" in out
    assert "validation: passed, 1 Jev requests" in out

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["max_revisions"] == 0
    assert "idea" not in sent_payload


def test_send_validate_to_backend_json_mode_prints_only_json(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATE_RESPONSE_BODY)):
        send_validate_to_backend(
            SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
            "## 1. Architecture overview\n\nSome text.", DUMMY_URL, json_mode=True,
        )

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["stage"] == "validated"


def test_send_validate_to_backend_writes_file_only_with_out(tmp_path):
    out_path = tmp_path / "out.md"
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATE_RESPONSE_BODY)):
        send_validate_to_backend(
            SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
            "## 1. Architecture overview\n\nSome text.", DUMMY_URL, out_path=str(out_path),
        )
    assert out_path.exists()


def test_send_validate_to_backend_without_out_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATE_RESPONSE_BODY)):
        send_validate_to_backend(
            SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
            "## 1. Architecture overview\n\nSome text.", DUMMY_URL,
        )
    assert not (tmp_path / "system-design.md").exists()


def test_send_validate_to_backend_revise_sends_max_revisions(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(200, VALIDATE_RESPONSE_BODY)) as mock_post:
        send_validate_to_backend(
            SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
            "## 1. Architecture overview\n\nSome text.", DUMMY_URL, max_revisions=2,
        )
    assert mock_post.call_args.kwargs["json"]["max_revisions"] == 2


def test_send_validate_to_backend_rate_limit_falls_back_to_fixed_message(capsys):
    with patch("systemiq.httpx.post", return_value=make_response(429, {})):
        with pytest.raises(SystemExit) as exc_info:
            send_validate_to_backend(
                SUCCESS_BODY["requirements"], FULL_SUCCESS_BODY["decisions"],
                "## 1. Architecture overview\n\nSome text.", DUMMY_URL,
            )
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "rate limited" in err


def test_main_requires_either_input_or_validate_saved(capsys):
    from systemiq import main
    with patch("sys.argv", ["systemiq"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "--validate-saved" in err


def test_main_validate_saved_sends_to_validate_endpoint(tmp_path):
    from systemiq import main

    saved_path = tmp_path / "saved.json"
    saved_path.write_text(_SAVED_RESPONSE_JSON, encoding="utf-8")

    captured = {"url": None, "payload": None}

    def capture_post(url, *, json, **kwargs):
        captured["url"] = url
        captured["payload"] = json
        return make_response(200, VALIDATE_RESPONSE_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", ["systemiq", "--validate-saved", str(saved_path)]):
            main()

    assert captured["url"].endswith("/validate")
    assert captured["payload"]["max_revisions"] == 0  # --revise not given
    assert "idea" not in captured["payload"]


def test_main_validate_saved_with_design_file_overrides_markdown(tmp_path):
    from systemiq import main

    saved_path = tmp_path / "saved.json"
    saved_path.write_text(_SAVED_RESPONSE_JSON, encoding="utf-8")
    design_path = tmp_path / "edited.md"
    design_path.write_text("## 1. Architecture overview\n\nEdited by hand.", encoding="utf-8")

    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, VALIDATE_RESPONSE_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", [
            "systemiq", "--validate-saved", str(saved_path), "--design-file", str(design_path),
        ]):
            main()

    assert "Edited by hand" in captured_payload["design_markdown"]
    assert "Original design text" not in captured_payload["design_markdown"]


def test_main_validate_saved_with_revise_sends_max_revisions(tmp_path):
    from systemiq import main

    saved_path = tmp_path / "saved.json"
    saved_path.write_text(_SAVED_RESPONSE_JSON, encoding="utf-8")
    captured_payload = {}

    def capture_post(url, *, json, **kwargs):
        captured_payload.update(json)
        return make_response(200, VALIDATE_RESPONSE_BODY)

    with patch("systemiq.httpx.post", side_effect=capture_post):
        with patch("sys.argv", [
            "systemiq", "--validate-saved", str(saved_path), "--revise", "--max-revisions", "2",
        ]):
            main()

    assert captured_payload["max_revisions"] == 2
