"""Tests for auto-numbered default output paths (next_free_path)."""

import builtins
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from systemiq import (
    DEFAULT_DESIGN_OUTPUT,
    DEFAULT_SAMPLE_OUTPUT,
    _finish_job_result,
    main,
    next_free_path,
    write_design_file,
)


# ── unit: next_free_path ───────────────────────────────────────────────────

class TestNextFreePath:
    def test_first_run_returns_original(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert next_free_path(Path("system-design.md")) == Path("system-design.md")

    def test_second_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first")
        assert next_free_path(Path("system-design.md")) == Path("system-design-2.md")

    def test_third_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first")
        (tmp_path / "system-design-2.md").write_text("second")
        assert next_free_path(Path("system-design.md")) == Path("system-design-3.md")

    def test_gap_reused_in_order(self, tmp_path, monkeypatch):
        """system-design.md exists, -2 free, -3 exists -> picks -2."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first")
        (tmp_path / "system-design-3.md").write_text("third")
        assert next_free_path(Path("system-design.md")) == Path("system-design-2.md")

    def test_sample_naming(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.SAMPLE.md").write_text("first")
        result = next_free_path(Path("system-design.SAMPLE.md"))
        assert result == Path("system-design.SAMPLE-2.md")

    def test_sample_third(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.SAMPLE.md").write_text("first")
        (tmp_path / "system-design.SAMPLE-2.md").write_text("second")
        result = next_free_path(Path("system-design.SAMPLE.md"))
        assert result == Path("system-design.SAMPLE-3.md")

    def test_1000_limit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("x")
        for n in range(2, 1002):
            (tmp_path / f"system-design-{n}.md").write_text("x")
        with pytest.raises(SystemExit) as exc_info:
            next_free_path(Path("system-design.md"))
        assert exc_info.value.code == 1


# ── unit: write_design_file exclusive mode ─────────────────────────────────

DESIGN_DATA = {
    "meta": {},
    "design_markdown": "## 1. Architecture\n\nContent.",
}


class TestWriteExclusive:
    def test_auto_creates_new_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = next_free_path(DEFAULT_DESIGN_OUTPUT)
        result = write_design_file(DESIGN_DATA, path, auto=True)
        assert result == Path("system-design.md")
        assert result.exists()

    def test_auto_race_retries(self, tmp_path, monkeypatch):
        """Simulate race: exclusive open fails once, then succeeds on -3."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first")
        path = next_free_path(DEFAULT_DESIGN_OUTPUT)
        assert path == Path("system-design-2.md")

        real_open = builtins.open
        raced = False

        def racing_open(p, mode="r", *a, **kw):
            nonlocal raced
            if mode == "x" and str(p).endswith("system-design-2.md") and not raced:
                raced = True
                Path(p).write_text("raced!")
                raise FileExistsError
            return real_open(p, mode, *a, **kw)

        monkeypatch.setattr("builtins.open", racing_open)
        result = write_design_file(DESIGN_DATA, path, auto=True)
        assert result == Path("system-design-3.md")
        assert result.exists()
        assert "Architecture" in result.read_text()


# ── integration: main() flows ─────────────────────────────────────────────

def _make_response(status_code, body):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if isinstance(body, (dict, list)):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = Exception("not JSON")
        resp.text = body
    return resp


def _healthz(hosted):
    return _make_response(200, {"status": "ok", "hosted": hosted, "max_idea_chars": 2000})


DONE_RESULT = {
    "stage": "validated",
    "requirements": {
        "project_summary": "A test", "app_type": "web", "core_features": [],
        "user_roles": [], "expected_scale": {"users": None, "peak_requests_per_second": None, "data_volume": None},
        "realtime": None, "geospatial": None, "authentication": None,
        "search_filtering": None, "media_storage": None, "payments": None,
        "offline_support": None, "external_integrations": [], "constraints": [],
        "assumptions": [], "unknowns": [],
    },
    "decisions": [],
    "meta": {"decision_model": "jev-1.13-free", "input_tokens": 1, "output_tokens": 1},
    "design_markdown": "## 1. Architecture overview\n\nSome text.",
    "design_warnings": [],
    "validation": [],
    "revisions": [],
}


class TestAutoNamingHosted:
    def test_second_run_auto_numbers(self, tmp_path, monkeypatch, capsys):
        """Default name exists -> auto-names to -2, design succeeds."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first run")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=_make_response(
                 202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
            mock_get.side_effect = [
                _healthz(True),
                _make_response(200, {
                    "status": "done", "stage": "done", "detail": None,
                    "position": None, "error": None, "result": DONE_RESULT,
                }),
            ]
            main()

        assert (tmp_path / "system-design.md").read_text() == "first run"
        assert (tmp_path / "system-design-2.md").exists()
        assert "Architecture" in (tmp_path / "system-design-2.md").read_text()

    def test_absolute_path_in_messages(self, tmp_path, monkeypatch, capsys):
        """Both the early and final messages show absolute paths."""
        monkeypatch.chdir(tmp_path)

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=_make_response(
                 202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes"]):
            mock_get.side_effect = [
                _healthz(True),
                _make_response(200, {
                    "status": "done", "stage": "done", "detail": None,
                    "position": None, "error": None, "result": DONE_RESULT,
                }),
            ]
            main()

        out = capsys.readouterr().out
        abspath = os.path.abspath("system-design.md")
        assert f"The design will be saved to {abspath}" in out
        assert f"design written to {abspath}" in out


class TestAutoNamingLocal:
    def test_second_run_auto_numbers(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first run")

        with patch("hosted_client.httpx.get", return_value=_healthz(False)), \
             patch("systemiq.httpx.post", return_value=_make_response(200, DONE_RESULT)), \
             patch("sys.argv", ["systemiq", "idea"]):
            main()

        assert (tmp_path / "system-design.md").read_text() == "first run"
        assert (tmp_path / "system-design-2.md").exists()


class TestAutoNamingJob:
    def test_job_auto_numbers(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first run")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("sys.argv", ["systemiq", "--job", "job1"]):
            mock_get.side_effect = [
                _healthz(True),
                _make_response(200, {
                    "status": "done", "stage": "done", "detail": None,
                    "position": None, "error": None, "result": DONE_RESULT,
                }),
            ]
            main()

        assert (tmp_path / "system-design.md").read_text() == "first run"
        assert (tmp_path / "system-design-2.md").exists()


class TestAutoNamingSample:
    def test_sample_auto_numbers(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.SAMPLE.md").write_text("first sample")

        index_resp = _make_response(200, [{"url": "https://github.com/TFD666/system-iq/blob/main/samples/1.md"}])
        md_resp = MagicMock(spec=httpx.Response)
        md_resp.text = "# Sample design"

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("sys.argv", ["systemiq", "--sample", "1"]):
            mock_get.side_effect = [index_resp, md_resp]
            main()

        assert (tmp_path / "system-design.SAMPLE.md").read_text() == "first sample"
        new_path = tmp_path / "system-design.SAMPLE-2.md"
        assert new_path.exists()
        assert "Sample design" in new_path.read_text()

    def test_sample_absolute_path_in_message(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        index_resp = _make_response(200, [{"url": "https://github.com/TFD666/system-iq/blob/main/samples/1.md"}])
        md_resp = MagicMock(spec=httpx.Response)
        md_resp.text = "# Sample design"

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("sys.argv", ["systemiq", "--sample", "1"]):
            mock_get.side_effect = [index_resp, md_resp]
            main()

        out = capsys.readouterr().out
        abspath = os.path.abspath("system-design.SAMPLE.md")
        assert f"sample written to {abspath}" in out


class TestExplicitOutStillErrors:
    def test_explicit_out_existing_errors(self, tmp_path, monkeypatch, capsys):
        """Explicit --out that already exists still errors with zero requests."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "my-design.md").write_text("existing")

        def _fail(*a, **kw):
            raise AssertionError("must not make any network request")

        with patch("hosted_client.httpx.get", side_effect=_fail), \
             patch("hosted_client.httpx.post", side_effect=_fail), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes",
                                "--out", "my-design.md"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        assert "already exists" in capsys.readouterr().err


class TestForceOverwrites:
    def test_force_overwrites_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("old")

        with patch("hosted_client.httpx.get", return_value=_healthz(False)), \
             patch("systemiq.httpx.post", return_value=_make_response(200, DONE_RESULT)), \
             patch("sys.argv", ["systemiq", "idea", "--force"]):
            main()

        content = (tmp_path / "system-design.md").read_text()
        assert "old" not in content
        assert "Architecture" in content


class TestDryRunAndJson:
    def test_dry_run_creates_no_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["systemiq", "idea", "--dry-run"]):
            main()
        assert not (tmp_path / "system-design.md").exists()

    def test_json_auto_names(self, tmp_path, monkeypatch, capsys):
        """--json with default name still auto-numbers and no early message on stdout."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system-design.md").write_text("first run")

        with patch("hosted_client.httpx.get") as mock_get, \
             patch("hosted_client.httpx.post", return_value=_make_response(
                 202, {"job_id": "j1", "status": "queued", "position": 1})), \
             patch("sys.argv", ["systemiq", "idea", "--access-code", "c", "--yes", "--json"]):
            mock_get.side_effect = [
                _healthz(True),
                _make_response(200, {
                    "status": "done", "stage": "done", "detail": None,
                    "position": None, "error": None, "result": DONE_RESULT,
                }),
            ]
            main()

        assert (tmp_path / "system-design.md").read_text() == "first run"
        assert (tmp_path / "system-design-2.md").exists()
        out = capsys.readouterr().out
        assert "The design will be saved to" not in out
