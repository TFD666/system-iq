"""
Tests for the early output-path check: the hosted flow must refuse before
sending anything if the design output file already exists, instead of
discovering it only after the run (and quota) is spent.
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from systemiq import _finish_job_result, main


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


def _healthz(hosted, max_idea_chars=2000):
    return make_response(200, {"status": "ok", "hosted": hosted, "max_idea_chars": max_idea_chars})


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
    "meta": {"decision_model": "jev-1.13-free", "input_tokens": 1, "output_tokens": 1},
    "design_markdown": "## 1. Architecture overview\n\nSome text.",
    "design_warnings": [],
    "validation": [],
    "revisions": [],
}


def _fail(*args, **kwargs):
    raise AssertionError("must not make any network request")


# ── hosted flow, new submission ──────────────────────────────────────────────

class TestHostedEarlyCheck:
    def test_existing_file_exits_1_with_zero_network(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("hosted_client.httpx.post", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "already exists" in err
        assert "--force" in err
        assert "--out" in err

    def test_force_proceeds(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("old")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--force"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()

        content = (tmp_path / "system-design.md").read_text()
        assert "old" not in content
        assert "## 1. Architecture overview" in content

    def test_new_out_path_proceeds(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("old")  # default path exists, but --out points elsewhere
        out_path = tmp_path / "other.md"

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=make_response(202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--out", str(out_path)]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()

        assert out_path.exists()

    def test_checked_before_mode_detection(self, tmp_path, monkeypatch):
        """The check must happen even before healthz -- not just before /jobs."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1


# ── local flow ─────────────────────────────────────────────────────────────

class TestLocalEarlyCheck:
    def test_existing_file_exits_1_with_zero_network(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("systemiq.httpx.post", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "already exists" in err

    def test_force_proceeds(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("old")

        with patch("hosted_client.httpx.get", return_value=_healthz(False)), \
             patch("systemiq.httpx.post", return_value=make_response(200, DONE_RESULT)), \
             patch("sys.argv", ["systemiq", "idea", "--force"]):
            main()

        content = (tmp_path / "system-design.md").read_text()
        assert "old" not in content


# ── --json / --dry-run unaffected ────────────────────────────────────────────

class TestJsonAndDryRunUnaffected:
    def test_dry_run_ignores_existing_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea", "--dry-run"]):
            main()  # must not raise, must not touch the existing file

        assert (tmp_path / "system-design.md").read_text() == "existing"

    def test_json_mode_still_checked(self, tmp_path, monkeypatch, capsys):
        """--json does not bypass the guard: the check applies the same either way."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("hosted_client.httpx.post", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--json"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1


# ── --job ─────────────────────────────────────────────────────────────────────

class TestJobEarlyCheck:
    def test_existing_file_fails_before_polling(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("existing")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "--job", "job1"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        assert "already exists" in capsys.readouterr().err

    def test_force_proceeds_to_poll(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("old")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("sys.argv", ["systemiq", "--job", "job1", "--force"]):
            mock_get.side_effect = [
                _healthz(True),
                make_response(200, {"status": "done", "stage": "done", "detail": None, "position": None, "error": None, "result": DONE_RESULT}),
            ]
            main()

        content = (tmp_path / "system-design.md").read_text()
        assert "old" not in content


# ── late safety net (race: file appears while the job runs) ─────────────────

class TestLateSafetyNet:
    def test_resume_hint_printed_when_file_appears_late(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("appeared while job ran")

        class FakeArgs:
            out = None
            force = False
            json = False

        with pytest.raises(SystemExit) as exc_info:
            _finish_job_result(DONE_RESULT, FakeArgs(), "job-xyz")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "already exists" in err
        assert "--job job-xyz" in err
        assert "--out" in err

    def test_force_overrides_late_check(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("appeared while job ran")

        class FakeArgs:
            out = None
            force = True
            json = False

        _finish_job_result(DONE_RESULT, FakeArgs(), "job-xyz")  # must not raise
        content = (tmp_path / "system-design.md").read_text()
        assert "appeared while job ran" not in content
