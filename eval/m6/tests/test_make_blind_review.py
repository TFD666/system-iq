"""Tests for eval/m6/make_blind_review.py. No network, standard library only."""

import csv
import json

import pytest

import make_blind_review as mb


def _write_run(runs_dir, run_id, idea, version, repeat, markdown):
    body = {"design_markdown": markdown}
    (runs_dir / f"{run_id}.json").write_text(json.dumps(body), encoding="utf-8")
    (runs_dir / f"{run_id}.meta.json").write_text(
        json.dumps({"idea": idea, "version": version, "repeat": repeat}), encoding="utf-8"
    )


@pytest.fixture
def _runs_dir(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(runs_dir, "idea1__A__r1", "idea1", "A", 1, "Design A text for idea1")
    _write_run(runs_dir, "idea1__B__r1", "idea1", "B", 1, "Design B text for idea1")
    _write_run(runs_dir, "idea2__A__r1", "idea2", "A", 1, "Design A text for idea2 only")
    return runs_dir


def test_order_is_deterministic_for_a_seed(tmp_path, _runs_dir):
    blind_dir_1 = tmp_path / "blind1"
    key_1 = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir_1)

    blind_dir_2 = tmp_path / "blind2"
    key_2 = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir_2)

    assert key_1 == key_2


def test_only_ideas_with_both_a_and_b_get_a_review(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    key = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir)

    assert "idea1" in key
    assert "idea2" not in key  # idea2 only has an A run
    assert (blind_dir / "idea1.md").exists()
    assert not (blind_dir / "idea2.md").exists()


def test_key_maps_x_and_y_to_a_and_b_and_stays_out_of_the_review_file(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    key = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir)

    assert set(key["idea1"].keys()) == {"X", "Y"}
    assert set(key["idea1"].values()) == {"A", "B"}

    review_text = (blind_dir / "idea1.md").read_text(encoding="utf-8")
    assert '"A"' not in review_text
    assert '"B"' not in review_text
    assert "Design X" in review_text
    assert "Design Y" in review_text


def test_review_file_contains_both_designs_and_a_rating_form(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir)

    content = (blind_dir / "idea1.md").read_text(encoding="utf-8")
    assert "Design A text for idea1" in content
    assert "Design B text for idea1" in content
    for field in mb.RATING_FIELDS:
        assert field in content


def test_section_13_is_stripped_from_the_blind_review_file(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(
        runs_dir, "idea1__A__r1", "idea1", "A", 1,
        "## 1. Architecture overview\n\ntext A\n\n## 13. Assumptions and open questions\n- secret A",
    )
    _write_run(
        runs_dir, "idea1__B__r1", "idea1", "B", 1,
        "## 1. Architecture overview\n\ntext B\n\n## 13. Assumptions and open questions\n- secret B",
    )

    blind_dir = tmp_path / "blind"
    key = mb.make_blind_reviews(seed=7, runs_dir=runs_dir, blind_dir=blind_dir)

    content = (blind_dir / "idea1.md").read_text(encoding="utf-8")
    assert "## 13." not in content
    assert "secret A" not in content and "secret B" not in content
    assert "text A" in content and "text B" in content
    # Key still maps X and Y to A and B correctly despite the stripped text.
    assert set(key["idea1"].keys()) == {"X", "Y"}
    assert set(key["idea1"].values()) == {"A", "B"}


def test_reveal_maps_x_y_ratings_back_to_a_b_averages(tmp_path):
    key_path = tmp_path / "blind_key.json"
    key_path.write_text(json.dumps({"idea1": {"X": "B", "Y": "A"}}), encoding="utf-8")

    ratings_path = tmp_path / "ratings.csv"
    with open(ratings_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["idea", "design", "specific", "correct", "useful", "clear"])
        writer.writerow(["idea1", "X", "4", "5", "4", "5"])  # X -> B
        writer.writerow(["idea1", "Y", "2", "3", "2", "3"])  # Y -> A

    averages = mb.reveal(ratings_path=ratings_path, key_path=key_path)

    assert averages["B"]["specific"] == 4.0
    assert averages["A"]["specific"] == 2.0
    assert averages["B"]["n"] == 1
    assert averages["A"]["n"] == 1
