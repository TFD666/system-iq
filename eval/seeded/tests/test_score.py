"""Tests for eval/seeded/score.py. No network, small fixed fixture."""

import json

import pytest

import score as sc

_GROUND_TRUTH = {
    "v00_base": {"expected_flagged": [], "description": "no defect"},
    "v01_missing": {"expected_flagged": ["val_missing_component"], "description": "missing component"},
}


def _result(entries, validation_model="jev-1.13-free", validation_input_tokens=10):
    # Real /validate shape: decision_model is always "n/a (validation only)",
    # so validation_model + a real token count is what marks a real Jev run.
    meta = {"validation_model": validation_model, "validation_input_tokens": validation_input_tokens}
    return {"meta": meta, "validation": entries}


@pytest.fixture
def _env(tmp_path, monkeypatch):
    ground_truth_path = tmp_path / "ground_truth.json"
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    ground_truth_path.write_text(json.dumps(_GROUND_TRUTH), encoding="utf-8")
    monkeypatch.setattr(sc, "GROUND_TRUTH_PATH", ground_truth_path)
    monkeypatch.setattr(sc, "RESULTS_DIR", results_dir)
    return ground_truth_path, results_dir


def test_scores_exact_tp_fn_fp_tn_both_views(_env):
    _, results_dir = _env
    # v00_base: not expected to flag val_missing_component, but Jev says "possible".
    (results_dir / "v00_base.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "possible", "probability": 0.5}])),
        encoding="utf-8",
    )
    # v01_missing: expected to flag val_missing_component, Jev says "flagged".
    (results_dir / "v01_missing.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "flagged", "probability": 0.9}])),
        encoding="utf-8",
    )

    data = sc.score()

    strict = data["overall"]["strict"]
    # strict: v00 not-expected/not-predicted(TN, "possible" isn't "flagged"); v01 expected/predicted(TP)
    assert strict == {"TP": 1, "FN": 0, "FP": 0, "TN": 1}

    lenient = data["overall"]["lenient"]
    # lenient: v00 not-expected/predicted("possible" counts) -> FP; v01 expected/predicted -> TP
    assert lenient == {"TP": 1, "FN": 0, "FP": 1, "TN": 0}

    assert data["pending"] == []
    assert data["misses"] == []
    assert data["false_positives"] == []


def test_lists_misses_and_false_positives_strict_view(_env):
    _, results_dir = _env
    # v00_base: not expected, but flagged -> false positive.
    (results_dir / "v00_base.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "flagged", "probability": 0.7}])),
        encoding="utf-8",
    )
    # v01_missing: expected, but satisfied -> miss.
    (results_dir / "v01_missing.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "satisfied", "probability": 0.1}])),
        encoding="utf-8",
    )

    data = sc.score()

    assert data["misses"] == [{"variant": "v01_missing", "id": "val_missing_component", "probability": 0.1}]
    assert data["false_positives"] == [
        {"variant": "v00_base", "id": "val_missing_component", "probability": 0.7}
    ]


def test_pending_lists_variants_with_no_result_file(_env):
    _, results_dir = _env
    (results_dir / "v00_base.json").write_text(json.dumps(_result([])), encoding="utf-8")

    data = sc.score()

    assert data["pending"] == ["v01_missing"]


def test_ignores_a_fake_result_and_reports_it(_env):
    _, results_dir = _env
    (results_dir / "v00_base.json").write_text(
        json.dumps(_result(
            [{"id": "val_missing_component", "status": "flagged", "probability": 0.9}],
            validation_model="fake (demo only)",
        )),
        encoding="utf-8",
    )
    (results_dir / "v01_missing.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "flagged", "probability": 0.9}])),
        encoding="utf-8",
    )

    data = sc.score()

    assert data["ignored"] == ["v00_base"]
    assert data["pending"] == []
    # The fake result must not count toward any TP/FN/FP/TN bucket.
    assert data["overall"]["strict"] == {"TP": 1, "FN": 0, "FP": 0, "TN": 0}
    report = sc.render_report(data)
    assert "Ignored (not a real Jev result): v00_base" in report


def test_ignores_a_result_with_zero_validation_tokens(_env):
    _, results_dir = _env
    (results_dir / "v00_base.json").write_text(
        json.dumps(_result(
            [{"id": "val_missing_component", "status": "flagged", "probability": 0.9}],
            validation_input_tokens=0,
        )),
        encoding="utf-8",
    )

    data = sc.score()

    assert data["ignored"] == ["v00_base"]


def test_render_report_is_ascii(_env):
    _, results_dir = _env
    (results_dir / "v00_base.json").write_text(
        json.dumps(_result([{"id": "val_missing_component", "status": "flagged", "probability": 0.7}])),
        encoding="utf-8",
    )
    data = sc.score()
    report = sc.render_report(data)
    assert report.isascii()
