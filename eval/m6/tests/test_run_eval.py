"""Tests for eval/m6/run_eval.py. No network: httpx.post is mocked."""

import json
from unittest.mock import patch

import pytest

import run_eval as re_


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _a_body(llm_model="qwen/qwen3-27b", group_stats=None):
    return {
        "stage": "designed",
        "design_markdown": "## 1. Architecture overview\n\ntext",
        "design_warnings": [],
        "meta": {
            "decision_model": "none (llm-only baseline)",
            "llm_model": llm_model,
            "design_group_stats": group_stats if group_stats is not None else [{"id": "g1", "elapsed_seconds": 1.0}],
        },
    }


def _b_body(decision_model="jev-1.13-free", validation_model="jev-1.13-free",
            validation_input_tokens=10, validation_status="flagged", writer_style=None):
    meta = {
        "decision_model": decision_model,
        "validation_model": validation_model,
        "validation_input_tokens": validation_input_tokens,
        "validation_status": validation_status,
        "validation_calls": 1,
    }
    if writer_style is not None:
        meta["writer_style"] = writer_style
    return {
        "stage": "validated",
        "design_markdown": "## 1. Architecture overview\n\ntext",
        "design_warnings": [],
        "validation": [],
        "meta": meta,
    }


@pytest.fixture
def _env(tmp_path, monkeypatch):
    ideas_dir = tmp_path / "ideas"
    runs_dir = tmp_path / "runs"
    ideas_dir.mkdir()
    (ideas_dir / "idea1.md").write_text("A nice idea about bars.", encoding="utf-8")
    (ideas_dir / "idea2.md").write_text("A nice idea about mojitos.", encoding="utf-8")
    monkeypatch.setattr(re_, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(re_, "time", __import__("time"))
    monkeypatch.setattr(re_.time, "sleep", lambda s: None)
    return ideas_dir, runs_dir


def _run(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_eval.py"] + argv)
    re_.main()


def test_builds_the_right_request_per_version(_env, monkeypatch):
    ideas_dir, _runs_dir = _env
    captured = []

    def capture_post(url, *, json, **kwargs):
        captured.append(json)
        body = _a_body() if json["mode"] == "llm_only" else _b_body()
        return _FakeResponse(200, body)

    with patch("run_eval.httpx.post", side_effect=capture_post):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--max-runs", "2"], monkeypatch)

    assert len(captured) == 2
    a_req = next(r for r in captured if r["mode"] == "llm_only")
    assert a_req["stage"] == "design"
    b_req = next(r for r in captured if r["mode"] == "pipeline")
    assert b_req["stage"] == "validate"
    assert b_req["max_revisions"] == 0


def test_skips_run_that_already_has_a_result(_env, monkeypatch, capsys):
    ideas_dir, runs_dir = _env
    runs_dir.mkdir()
    (runs_dir / "idea1__A__r1.json").write_text("{}", encoding="utf-8")
    (runs_dir / "idea1__A__r1.meta.json").write_text("{}", encoding="utf-8")

    with patch("run_eval.httpx.post", return_value=_FakeResponse(200, _a_body())) as mock_post:
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "A", "--max-runs", "5"], monkeypatch)

    assert mock_post.call_count == 0
    out = capsys.readouterr().out
    assert "skip (already has a result): idea1__A__r1" in out


def test_honors_max_runs(_env, monkeypatch, capsys):
    ideas_dir, _runs_dir = _env

    def side_effect(url, *, json, **kwargs):
        return _FakeResponse(200, _a_body() if json["mode"] == "llm_only" else _b_body())

    with patch("run_eval.httpx.post", side_effect=side_effect) as mock_post:
        _run(["--ideas-dir", str(ideas_dir), "--max-runs", "2"], monkeypatch)

    assert mock_post.call_count == 2
    out = capsys.readouterr().out
    assert "max runs (2) reached" in out


def test_stops_on_non_200_without_saving(_env, monkeypatch, capsys):
    ideas_dir, runs_dir = _env
    with patch("run_eval.httpx.post", return_value=_FakeResponse(429, {"detail": "rate limited"})):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "A", "--max-runs", "5"], monkeypatch)

    assert not (runs_dir / "idea1__A__r1.json").exists()
    out = capsys.readouterr().out
    assert "HTTP 429: rate limited" in out
    assert "stopped early" in out


@pytest.mark.parametrize("decision_model,validation_model", [
    ("fake (demo only)", "fake (demo only)"),
    ("jev-1.13-free", "replay (saved)"),
])
def test_refuses_to_save_fake_or_replay_b_runs(_env, monkeypatch, capsys, decision_model, validation_model):
    ideas_dir, runs_dir = _env
    body = _b_body(decision_model=decision_model, validation_model=validation_model)
    with patch("run_eval.httpx.post", return_value=_FakeResponse(200, body)):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "B", "--max-runs", "5"], monkeypatch)

    assert not (runs_dir / "idea1__B__r1.json").exists()
    out = capsys.readouterr().out
    assert "not a real run" in out
    assert "not saving" in out


@pytest.mark.parametrize("status", [502, 503, 504])
def test_retries_once_on_transient_status_then_saves(_env, monkeypatch, capsys, status):
    ideas_dir, runs_dir = _env
    responses = [_FakeResponse(status, {"detail": "upstream hiccup"}), _FakeResponse(200, _a_body())]

    with patch("run_eval.httpx.post", side_effect=responses) as mock_post:
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "A", "--max-runs", "5"], monkeypatch)

    assert mock_post.call_count == 2
    assert (runs_dir / "idea1__A__r1.json").exists()
    out = capsys.readouterr().out
    assert "transient upstream error, retrying once" in out


def test_transient_retry_failing_again_stops_as_usual(_env, monkeypatch, capsys):
    ideas_dir, runs_dir = _env
    responses = [_FakeResponse(503, {"detail": "still down"}), _FakeResponse(503, {"detail": "still down"})]

    with patch("run_eval.httpx.post", side_effect=responses) as mock_post:
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "A", "--max-runs", "5"], monkeypatch)

    assert mock_post.call_count == 2  # original + the one retry, never more
    assert not (runs_dir / "idea1__A__r1.json").exists()
    out = capsys.readouterr().out
    assert "HTTP 503" in out
    assert "stopped early" in out


def test_never_retries_a_429(_env, monkeypatch, capsys):
    ideas_dir, runs_dir = _env
    with patch("run_eval.httpx.post", return_value=_FakeResponse(429, {"detail": "rate limited"})) as mock_post:
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "A", "--max-runs", "5"], monkeypatch)

    assert mock_post.call_count == 1  # no retry for 429
    assert not (runs_dir / "idea1__A__r1.json").exists()
    out = capsys.readouterr().out
    assert "transient upstream error" not in out
    assert "HTTP 429" in out


def test_b2_request_sets_writer_style_confident(_env, monkeypatch):
    ideas_dir, _runs_dir = _env
    captured = []

    def capture_post(url, *, json, **kwargs):
        captured.append(json)
        return _FakeResponse(200, _b_body(writer_style="confident"))

    with patch("run_eval.httpx.post", side_effect=capture_post):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "B2", "--max-runs", "5"], monkeypatch)

    assert len(captured) == 1
    req = captured[0]
    assert req["mode"] == "pipeline"
    assert req["stage"] == "validate"
    assert req["max_revisions"] == 0
    assert req["writer_style"] == "confident"


def test_b_request_never_sets_writer_style(_env, monkeypatch):
    ideas_dir, _runs_dir = _env
    captured = []

    def capture_post(url, *, json, **kwargs):
        captured.append(json)
        return _FakeResponse(200, _b_body())

    with patch("run_eval.httpx.post", side_effect=capture_post):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "B", "--max-runs", "5"], monkeypatch)

    assert "writer_style" not in captured[0]


def test_b2_run_rejected_when_writer_style_is_not_confident(_env, monkeypatch, capsys):
    ideas_dir, runs_dir = _env
    with patch("run_eval.httpx.post", return_value=_FakeResponse(200, _b_body(writer_style="hedged"))):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "B2", "--max-runs", "5"], monkeypatch)

    assert not (runs_dir / "idea1__B2__r1.json").exists()
    out = capsys.readouterr().out
    assert "not a real run" in out
    assert "writer_style" in out


def test_saves_real_b2_run_with_meta(_env, monkeypatch):
    ideas_dir, runs_dir = _env
    with patch("run_eval.httpx.post", return_value=_FakeResponse(200, _b_body(writer_style="confident"))):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--only-version", "B2", "--max-runs", "5"], monkeypatch)

    assert (runs_dir / "idea1__B2__r1.json").exists()
    meta = json.loads((runs_dir / "idea1__B2__r1.meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == "B2"


def test_saves_real_a_and_b_runs_with_meta(_env, monkeypatch):
    ideas_dir, runs_dir = _env

    def side_effect(url, *, json, **kwargs):
        return _FakeResponse(200, _a_body() if json["mode"] == "llm_only" else _b_body())

    with patch("run_eval.httpx.post", side_effect=side_effect):
        _run(["--ideas-dir", str(ideas_dir), "--only-idea", "idea1", "--max-runs", "5"], monkeypatch)

    a_meta = json.loads((runs_dir / "idea1__A__r1.meta.json").read_text(encoding="utf-8"))
    assert a_meta["idea"] == "idea1"
    assert a_meta["version"] == "A"
    assert "seconds" in a_meta
    assert (runs_dir / "idea1__B__r1.json").exists()
