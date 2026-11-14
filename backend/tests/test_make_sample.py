"""Tests for scripts/make_sample.py."""

import importlib.util
import json
import os
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mod():
    """Import make_sample.py from scripts/ directory."""
    scripts_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "scripts"),
    )
    spec = importlib.util.spec_from_file_location(
        "make_sample",
        os.path.join(scripts_dir, "make_sample.py"),
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _good_md():
    return "\n".join(f"## {i+1}. Section {i+1}\nContent." for i in range(13))


def _fake_resp(md=None, warnings=None, val_status="passed"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "design_markdown": md if md is not None else _good_md(),
        "design_warnings": warnings or [],
        "validation": [],
        "meta": {"validation_status": val_status},
    }
    return resp


class TestMakeSample:
    def test_success(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("Build a todo app")
        out = str(tmp_path / "out.md")
        idx = tmp_path / "index.json"
        idx.write_text("[]")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        assert mod.run(str(idea), "Todo App", out, "http://f", "pipeline", str(idx)) == 0
        assert os.path.exists(out)
        content = open(out).read()
        assert "SAMPLE:" in content
        assert "pipeline v1.0" in content
        entries = json.loads(idx.read_text())
        assert len(entries) == 1
        assert entries[0]["title"] == "Todo App"

    def test_wrong_section_count(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(md="## 1. Only\nContent.")

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 1
        assert not os.path.exists(out)

    def test_fallback_lines(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        sections = [f"## {i+1}. S\nContent." for i in range(13)]
        sections[5] = "## 6. S\nThis could not be generated properly."
        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(md="\n".join(sections))

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 1

    def test_design_warnings(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(warnings=["bad thing"])

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 1

    def test_validation_skipped(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(val_status="skipped")

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 1

    def test_index_no_duplicates(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")
        idx = tmp_path / "index.json"
        idx.write_text('[{"title":"Existing","url":"http://x"}]')

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        mod.run(str(idea), "Existing", out, "http://f", "pipeline", str(idx))
        entries = json.loads(idx.read_text())
        assert sum(1 for e in entries if e["title"] == "Existing") == 1
