"""Tests for eval/seeded/run_seeded.py. No network: httpx.post is mocked."""

import json
from unittest.mock import patch

import pytest

import run_seeded as rs


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _ok_body(status="flagged", validation_model: str | None = "jev-1.13-free", validation_input_tokens=10):
    # Real /validate shape: decision_model is always fixed to "n/a (validation
    # only)" there, so validation_model is what tells a real Jev run apart.
    meta = {
        "validation_status": status,
        "decision_model": "n/a (validation only)",
        "validation_input_tokens": validation_input_tokens,
    }
    if validation_model is not None:
        meta["validation_model"] = validation_model
    return {"meta": meta, "validation": []}


@pytest.fixture
def _env(tmp_path, monkeypatch):
    variants_dir = tmp_path / "variants"
    results_dir = tmp_path / "results"
    variants_dir.mkdir()
    for vid in ("v00_base", "v01_missing_component", "v02_invented_feature"):
        (variants_dir / f"{vid}.md").write_text(f"design text for {vid}", encoding="utf-8")
    monkeypatch.setattr(rs, "VARIANTS_DIR", variants_dir)
    monkeypatch.setattr(rs, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(rs, "load_requirements_and_decisions", lambda path: ({"project_summary": "x"}, []))
    monkeypatch.setattr(rs, "time", __import__("time"))
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    return variants_dir, results_dir


def _run(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_seeded.py"] + argv)
    rs.main()


def test_skips_variant_that_already_has_a_result(_env, monkeypatch, capsys):
    _, results_dir = _env
    results_dir.mkdir()
    (results_dir / "v00_base.json").write_text("{}", encoding="utf-8")

    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body())) as mock_post:
        _run(["--limit", "10"], monkeypatch)

    assert not any("v00_base" in str(c) for c in mock_post.call_args_list)
    out = capsys.readouterr().out
    assert "skip (already has a result): v00_base" in out


def test_honors_limit(_env, monkeypatch, capsys):
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body())) as mock_post:
        _run(["--limit", "2"], monkeypatch)

    assert mock_post.call_count == 2
    out = capsys.readouterr().out
    assert "request limit (2) reached" in out
    assert "pending: v02_invented_feature" in out


def test_stops_on_non_200_and_does_not_save(_env, monkeypatch, capsys):
    _, results_dir = _env
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(500, {})):
        _run(["--limit", "10"], monkeypatch)

    assert not (results_dir / "v00_base.json").exists()
    out = capsys.readouterr().out
    assert "HTTP 500" in out
    assert "stopped early" in out


def test_stops_on_skipped_status_without_saving(_env, monkeypatch, capsys):
    _, results_dir = _env
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body(status="skipped"))):
        _run(["--limit", "10"], monkeypatch)

    assert not (results_dir / "v00_base.json").exists()
    out = capsys.readouterr().out
    assert "validation_status is skipped" in out


@pytest.mark.parametrize("validation_model,label", [("fake (demo only)", "fake"), ("replay (saved)", "replay")])
def test_refuses_to_save_fake_or_replay_results(_env, monkeypatch, capsys, validation_model, label):
    _, results_dir = _env
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body(validation_model=validation_model))):
        _run(["--limit", "10"], monkeypatch)

    assert not (results_dir / "v00_base.json").exists()
    out = capsys.readouterr().out
    assert f"decision provider is {label}" in out


def test_refuses_to_save_when_validation_model_is_missing(_env, monkeypatch, capsys):
    _, results_dir = _env
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body(validation_model=None))):
        _run(["--limit", "10"], monkeypatch)

    assert not (results_dir / "v00_base.json").exists()
    out = capsys.readouterr().out
    assert "validation_model missing" in out


@pytest.mark.parametrize("tokens", [0, None])
def test_refuses_to_save_when_validation_input_tokens_is_zero_or_missing(_env, monkeypatch, capsys, tokens):
    _, results_dir = _env
    body = _ok_body(validation_input_tokens=tokens)
    if tokens is None:
        del body["meta"]["validation_input_tokens"]
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, body)):
        _run(["--limit", "10"], monkeypatch)

    assert not (results_dir / "v00_base.json").exists()
    out = capsys.readouterr().out
    assert "validation_input_tokens is 0 or missing" in out


def test_saves_real_result_and_prints_no_design_text(_env, monkeypatch, capsys):
    variants_dir, results_dir = _env
    with patch("run_seeded.httpx.post", return_value=_FakeResponse(200, _ok_body())):
        _run(["--limit", "1"], monkeypatch)

    saved = json.loads((results_dir / "v00_base.json").read_text(encoding="utf-8"))
    assert saved["meta"]["validation_status"] == "flagged"
    out = capsys.readouterr().out
    assert out.isascii()
    for path in variants_dir.glob("*.md"):
        assert path.read_text(encoding="utf-8") not in out
