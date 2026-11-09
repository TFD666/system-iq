"""Tests for eval/m6/make_blind_review.py. No network, standard library only."""

import csv
import json

import pytest

import make_blind_review as mb

# make_blind_reviews()'s key_path defaults to the real eval/m6/blind_key.json
# (a plain function-default value, bound once at import time -- monkeypatching
# mb.BLIND_KEY_PATH afterwards does NOT change it). Every call below must
# pass key_path explicitly, or it silently overwrites the real file.


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
    key_1 = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir_1, key_path=tmp_path / "key1.json")

    blind_dir_2 = tmp_path / "blind2"
    key_2 = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir_2, key_path=tmp_path / "key2.json")

    assert key_1 == key_2


def test_only_ideas_with_both_a_and_b_get_a_review(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    key = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir, key_path=tmp_path / "key.json")

    assert "idea1" in key
    assert "idea2" not in key  # idea2 only has an A run
    assert (blind_dir / "idea1.md").exists()
    assert not (blind_dir / "idea2.md").exists()


def test_key_maps_x_and_y_to_a_and_b_and_stays_out_of_the_review_file(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    key = mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir, key_path=tmp_path / "key.json")

    assert set(key["idea1"].keys()) == {"X", "Y"}
    assert set(key["idea1"].values()) == {"A", "B"}

    review_text = (blind_dir / "idea1.md").read_text(encoding="utf-8")
    assert '"A"' not in review_text
    assert '"B"' not in review_text
    assert "Design X" in review_text
    assert "Design Y" in review_text


def test_review_file_contains_both_designs_and_a_rating_form(tmp_path, _runs_dir):
    blind_dir = tmp_path / "blind"
    mb.make_blind_reviews(seed=7, runs_dir=_runs_dir, blind_dir=blind_dir, key_path=tmp_path / "key.json")

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
    key = mb.make_blind_reviews(seed=7, runs_dir=runs_dir, blind_dir=blind_dir, key_path=tmp_path / "key.json")

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


def test_reveal_report_table_prints_each_field_once_even_if_listed_twice(tmp_path, monkeypatch):
    # RATING_FIELDS listing "useful" twice must not print it twice in the
    # appended table or the rating form -- each field is deduped on output.
    monkeypatch.setattr(mb, "RATING_FIELDS", ("specific", "correct", "useful", "useful", "clear"))

    key_path = tmp_path / "blind_key.json"
    key_path.write_text(json.dumps({"idea1": {"X": "A", "Y": "B"}}), encoding="utf-8")
    ratings_path = tmp_path / "ratings.csv"
    with open(ratings_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["idea", "design", "specific", "correct", "useful", "clear"])
        writer.writerow(["idea1", "X", "4", "5", "4", "5"])

    averages = mb.reveal(ratings_path=ratings_path, key_path=key_path)
    report_path = tmp_path / "report.md"
    report_path.write_text("", encoding="utf-8")
    mb._append_averages_to_report(averages, report_path=report_path)

    report = report_path.read_text(encoding="utf-8")
    assert report.count("| useful |") == 1
    assert "| useful |\n| useful |" not in report

    form = mb._rating_form()
    assert form.count("- useful: ") == 1


# ── three-way (round 2) blind review ────────────────────────────────────────

@pytest.fixture
def _three_arm_runs_dir(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(runs_dir, "idea1__A__r1", "idea1", "A", 1, "Design A text for idea1")
    _write_run(runs_dir, "idea1__B__r1", "idea1", "B", 1, "Design B text for idea1")
    _write_run(runs_dir, "idea1__B2__r1", "idea1", "B2", 1, "Design B2 text for idea1")
    # A second repeat that must never be used (only r1 counts).
    _write_run(runs_dir, "idea1__A__r2", "idea1", "A", 2, "Design A repeat-2 text (must not appear)")
    # idea2 is missing its B2 run -- must be excluded entirely.
    _write_run(runs_dir, "idea2__A__r1", "idea2", "A", 1, "Design A text for idea2")
    _write_run(runs_dir, "idea2__B__r1", "idea2", "B", 1, "Design B text for idea2")
    return runs_dir


def test_three_way_order_is_deterministic_for_a_seed(tmp_path, _three_arm_runs_dir):
    key_1 = mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=tmp_path / "b1", key_path=tmp_path / "k1.json",
    )
    key_2 = mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=tmp_path / "b2", key_path=tmp_path / "k2.json",
    )
    assert key_1 == key_2


def test_three_way_only_ideas_with_every_arm_and_r1_get_a_review(tmp_path, _three_arm_runs_dir):
    blind3_dir = tmp_path / "blind3"
    key = mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=tmp_path / "key.json",
    )
    assert "idea1" in key
    assert "idea2" not in key  # missing a B2 run
    assert (blind3_dir / "idea1.md").exists()
    assert not (blind3_dir / "idea2.md").exists()


def test_three_way_key_covers_x_y_z_maps_to_arms_and_stays_out_of_review_file(tmp_path, _three_arm_runs_dir):
    blind3_dir = tmp_path / "blind3"
    key = mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=tmp_path / "key.json",
    )
    assert set(key["idea1"].keys()) == {"X", "Y", "Z"}
    assert set(key["idea1"].values()) == {"A", "B", "B2"}

    review_text = (blind3_dir / "idea1.md").read_text(encoding="utf-8")
    assert '"A"' not in review_text
    assert '"B"' not in review_text
    assert '"B2"' not in review_text
    assert "Design X" in review_text and "Design Y" in review_text and "Design Z" in review_text


def test_three_way_review_file_has_a_rating_form_per_design_and_only_r1_text(tmp_path, _three_arm_runs_dir):
    blind3_dir = tmp_path / "blind3"
    mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=tmp_path / "key.json",
    )
    content = (blind3_dir / "idea1.md").read_text(encoding="utf-8")

    assert "Design A text for idea1" in content
    assert "Design B text for idea1" in content
    assert "Design B2 text for idea1" in content
    assert "repeat-2" not in content  # only r1 is ever used

    assert content.count("Rating: Design") == 3
    for field in mb.RATING_FIELDS:
        assert content.count(f"- {field}: ") == 3  # one rating form per design


def test_three_way_strips_section_13(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    for version in ("A", "B", "B2"):
        _write_run(
            runs_dir, f"idea1__{version}__r1", "idea1", version, 1,
            f"## 1. Architecture overview\n\ntext {version}\n\n"
            f"## 13. Assumptions and open questions\n- secret {version}",
        )
    blind3_dir = tmp_path / "blind3"
    mb.make_three_way_blind_reviews(
        seed=11, runs_dir=runs_dir, blind3_dir=blind3_dir, key_path=tmp_path / "key.json",
    )
    content = (blind3_dir / "idea1.md").read_text(encoding="utf-8")
    assert "## 13." not in content
    for version in ("A", "B", "B2"):
        assert f"secret {version}" not in content
        assert f"text {version}" in content


def test_three_way_refuses_to_overwrite_without_force(tmp_path, _three_arm_runs_dir):
    blind3_dir = tmp_path / "blind3"
    key_path = tmp_path / "key.json"
    mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=key_path,
    )

    with pytest.raises(FileExistsError):
        mb.make_three_way_blind_reviews(
            seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=key_path,
        )

    # force=True overwrites without raising.
    mb.make_three_way_blind_reviews(
        seed=11, runs_dir=_three_arm_runs_dir, blind3_dir=blind3_dir, key_path=key_path, force=True,
    )


def test_reveal_three_way_averages_win_counts_and_ties_are_exact(tmp_path):
    key_path = tmp_path / "blind3_key.json"
    key_path.write_text(json.dumps({
        "idea1": {"X": "A", "Y": "B", "Z": "B2"},
        "idea2": {"X": "B", "Y": "B2", "Z": "A"},
        "idea3": {"X": "B2", "Y": "A", "Z": "B"},
    }), encoding="utf-8")

    ratings_path = tmp_path / "ratings.csv"
    with open(ratings_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["idea", "design", "specific", "correct", "useful", "clear"])
        # idea1: A=X overall 3.0, B=Y overall 4.0, B2=Z overall 5.0 -- B2 wins
        writer.writerow(["idea1", "X", "3", "3", "3", "3"])
        writer.writerow(["idea1", "Y", "4", "4", "4", "4"])
        writer.writerow(["idea1", "Z", "5", "5", "5", "5"])
        # idea2: B=X overall 2.0, B2=Y overall 2.0, A=Z overall 1.0 -- tie between B and B2
        writer.writerow(["idea2", "X", "2", "2", "2", "2"])
        writer.writerow(["idea2", "Y", "2", "2", "2", "2"])
        writer.writerow(["idea2", "Z", "1", "1", "1", "1"])
        # idea3: B2=X overall 5.0, A=Y overall 1.0, B=Z overall 1.0 -- B2 wins
        writer.writerow(["idea3", "X", "5", "5", "5", "5"])
        writer.writerow(["idea3", "Y", "1", "1", "1", "1"])
        writer.writerow(["idea3", "Z", "1", "1", "1", "1"])

    result = mb.reveal_three_way(ratings_path=ratings_path, key_path=key_path)

    assert result["averages"]["A"]["specific"] == pytest.approx((3 + 1 + 1) / 3)
    assert result["averages"]["B"]["n"] == 3
    assert result["wins"] == {"A": 0, "B": 0, "B2": 2}
    assert result["ties"] == 1


def test_three_way_reveal_report_prints_each_field_once(tmp_path):
    key_path = tmp_path / "blind3_key.json"
    key_path.write_text(json.dumps({"idea1": {"X": "A", "Y": "B", "Z": "B2"}}), encoding="utf-8")
    ratings_path = tmp_path / "ratings.csv"
    with open(ratings_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["idea", "design", "specific", "correct", "useful", "clear"])
        writer.writerow(["idea1", "X", "3", "3", "3", "3"])
        writer.writerow(["idea1", "Y", "4", "4", "4", "4"])
        writer.writerow(["idea1", "Z", "5", "5", "5", "5"])

    result = mb.reveal_three_way(ratings_path=ratings_path, key_path=key_path)
    report_path = tmp_path / "report.md"
    report_path.write_text("", encoding="utf-8")
    mb._append_three_way_averages_to_report(result, report_path=report_path)

    report = report_path.read_text(encoding="utf-8")
    assert report.count("| useful |") == 1
    assert "## Blind review round 2 (three arms)" in report
    assert report.isascii()
