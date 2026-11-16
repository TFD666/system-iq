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


def _fake_resp(md=None, warnings=None, val_status="passed", validation=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "design_markdown": md if md is not None else _good_md(),
        "design_warnings": warnings or [],
        "validation": validation or [],
        "meta": {"validation_status": val_status},
    }
    return resp


def _val(id_, status, probability):
    return {"id": id_, "status": status, "probability": probability, "text": "x", "sections": []}


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

    def test_non_validation_design_warnings_no_longer_block_acceptance(self, mod, monkeypatch, tmp_path):
        """
        Behavior change: acceptance used to require 0 design_warnings outright.
        It now requires only sections==13, 0 fallback lines, validation status
        not skipped, and flagged/possible counts within the (now explicit)
        thresholds -- a generic design_warnings entry unrelated to validation
        (e.g. "missing heading") no longer blocks acceptance by itself, since
        the flagged/possible counts (computed from "validation") are what the
        rule actually measures now.
        """
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(warnings=["missing heading: ## 7. Caching"])

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 0

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


# ── --max-flagged / --max-possible rule combinations ─────────────────────────

class TestRuleThresholds:
    def test_default_rejects_any_flagged_or_possible(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[_val("val_a", "possible", 0.5)])

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json")) == 1
        assert not os.path.exists(out)

    def test_max_possible_allows_possible_within_limit(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[
            _val("val_a", "possible", 0.5), _val("val_b", "ok", 0.9),
        ])

        assert mod.run(
            str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"),
            max_flagged=0, max_possible=2,
        ) == 0
        assert os.path.exists(out)

    def test_max_flagged_allows_flagged_within_limit(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[_val("val_a", "flagged", 0.1)])

        assert mod.run(
            str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"),
            max_flagged=1, max_possible=0,
        ) == 0
        assert os.path.exists(out)

    def test_exceeding_max_possible_still_rejects(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[
            _val("val_a", "possible", 0.5), _val("val_b", "possible", 0.4), _val("val_c", "possible", 0.3),
        ])

        assert mod.run(
            str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"),
            max_flagged=0, max_possible=2,
        ) == 1


# ── URL fix: forward slashes from --out, heal backslashes in existing index ─

class TestUrlFix:
    def test_windows_style_out_path_gives_forward_slash_url(self, mod, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        (tmp_path / "samples").mkdir()
        out = "samples\\x.md"  # a relative, Windows-style --out value
        idx = tmp_path / "index.json"
        idx.write_text("[]")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        assert mod.run(str(idea), "T", out, "http://f", "pipeline", str(idx)) == 0
        entries = json.loads(idx.read_text())
        assert entries[0]["url"] == "https://github.com/TFD666/system-iq/blob/main/samples/x.md"
        assert "\\" not in entries[0]["url"]

    def test_dot_slash_prefix_stripped(self, mod, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        idx = tmp_path / "index.json"
        idx.write_text("[]")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        mod.run(str(idea), "T", "./out.md", "http://f", "pipeline", str(idx))
        entries = json.loads(idx.read_text())
        assert entries[0]["url"] == "https://github.com/TFD666/system-iq/blob/main/out.md"

    def test_heals_backslash_in_existing_index_entry(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")
        idx = tmp_path / "index.json"
        idx.write_text(json.dumps([
            {"title": "Old", "url": "https://github.com/TFD666/system-iq/blob/main/samples\\old.md"},
        ]))

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        mod.run(str(idea), "T", out, "http://f", "pipeline", str(idx))
        entries = json.loads(idx.read_text())
        old_entry = next(e for e in entries if e["title"] == "Old")
        assert "\\" not in old_entry["url"]
        assert old_entry["url"] == "https://github.com/TFD666/system-iq/blob/main/samples/old.md"


# ── diagnostics on rejection (ids/status/probability only, no text) ──────────

class TestDiagnostics:
    def test_prints_non_ok_ids_statuses_percents_and_counts(self, mod, monkeypatch, tmp_path, capsys):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(
            md="## 1. Only\nContent.",  # force rejection via section count
            validation=[
                _val("val_auth", "flagged", 0.2),
                _val("val_db", "possible", 0.55),
                _val("val_cache", "ok", 0.9),
            ],
        )

        mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"))

        out_text = capsys.readouterr().out
        assert "val_auth flagged 20%" in out_text
        assert "val_db possible 55%" in out_text
        assert "val_cache" not in out_text  # ok results are not listed individually
        assert "ok=1 possible=1 flagged=1" in out_text

    def test_never_prints_idea_or_design_text(self, mod, monkeypatch, tmp_path, capsys):
        idea = tmp_path / "idea.txt"
        secret_idea_text = "a very secret project idea nobody should see in logs"
        idea.write_text(secret_idea_text)
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(
            md="## 1. Only\nContent.",
            validation=[_val("val_auth", "flagged", 0.2)],
        )

        mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"))

        captured = capsys.readouterr()
        assert secret_idea_text not in captured.out
        assert secret_idea_text not in captured.err


# ── header lines on acceptance ────────────────────────────────────────────────

class TestHeaderLines:
    def test_header_has_validation_summary_and_rule(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[
            _val("val_a", "possible", 0.5), _val("val_b", "ok", 0.9),
        ])

        mod.run(
            str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"),
            max_flagged=0, max_possible=2,
        )

        content = open(out).read()
        assert "rule: max-flagged 0, max-possible 2" in content
        assert "pipeline v1.0" in content
        assert "Validation by Jev: 1 ok, 1 possible, 0 flagged" in content
        assert "Findings: val_a (possible 50%)" in content

    def test_header_omits_findings_line_when_all_ok(self, mod, monkeypatch, tmp_path):
        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp(validation=[_val("val_a", "ok", 0.9)])

        mod.run(str(idea), "T", out, "http://f", "pipeline", str(tmp_path / "i.json"))

        content = open(out).read()
        assert "Findings:" not in content
        assert "Validation by Jev: 1 ok, 0 possible, 0 flagged" in content


# ── samples/README.md is never overwritten by the script ────────────────────

class TestReadmeUntouched:
    def test_script_does_not_touch_readme(self, mod, monkeypatch, tmp_path):
        readme = tmp_path / "README.md"
        original = "Samples are unedited pipeline output.\n"
        readme.write_text(original)

        idea = tmp_path / "idea.txt"
        idea.write_text("test")
        out = str(tmp_path / "out.md")
        idx = tmp_path / "index.json"
        idx.write_text("[]")

        monkeypatch.setattr(mod, "httpx", MagicMock())
        mod.httpx.post.return_value = _fake_resp()

        mod.run(str(idea), "T", out, "http://f", "pipeline", str(idx))

        assert readme.read_text() == original
