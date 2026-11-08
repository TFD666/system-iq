"""Tests for eval/seeded/make_variants.py. No network, standard library only."""

import json

import pytest

import make_variants as mv


# ── apply_section_mutation (the generic engine) ─────────────────────────────

_TINY = (
    "## 1. One\n\nFirst section text.\n\n"
    "## 2. Two\n\nSecond section text.\n\n"
    "## 3. Three\n\nThird section text.\n"
)


def test_mutation_changes_target_section_and_leaves_others_identical():
    new_text = mv.apply_section_mutation(
        _TINY, 2, lambda s: s.replace("Second", "Edited"), "test_variant"
    )
    assert "Edited section text" in new_text
    # Sections 1 and 3 are byte-identical to the original.
    assert mv.section_texts(new_text)[1] == mv.section_texts(_TINY)[1]
    assert mv.section_texts(new_text)[3] == mv.section_texts(_TINY)[3]


def test_mutation_that_changes_nothing_raises_a_clear_error():
    with pytest.raises(ValueError, match="my_variant"):
        mv.apply_section_mutation(_TINY, 2, lambda s: s, "my_variant")


def test_mutation_on_missing_section_raises_a_clear_error():
    with pytest.raises(ValueError, match="my_variant"):
        mv.apply_section_mutation(_TINY, 99, lambda s: s + "x", "my_variant")


# ── the real base design + specific variant behavior ────────────────────────

BASE = mv.BASE_PATH.read_text(encoding="utf-8")


def test_v01_removes_data_source_mentions_but_keeps_map_provider():
    text = mv._mutate_v01(BASE, "v01_missing_component")
    lowered = text.lower()
    assert "venue data source" not in lowered
    assert "venue directory" not in lowered
    assert "imported dataset" not in lowered
    assert "map provider" in lowered  # must survive in sections 2 and 8


def test_v03_changes_restful_too():
    text = mv._mutate_v03(BASE, "v03_decision_violated_api")
    section_4 = mv.section_texts(text)[4]
    assert "restful" not in section_4.lower()
    assert "rest" not in section_4.lower()
    assert "GraphQL" in section_4
    # Section 12 also says "REST" in the base -- that must be untouched.
    assert "REST" in mv.section_texts(text)[12]


def test_v04_replaces_every_postgis_occurrence():
    text = mv._mutate_v04(BASE, "v04_decision_violated_db")
    assert "PostGIS" not in mv.section_texts(text)[5]
    assert "MongoDB" in mv.section_texts(text)[5]


def test_v08_keeps_the_heading_but_replaces_the_body():
    text = mv._mutate_v08(BASE, "v08_incoherent")
    section_6 = mv.section_texts(text)[6]
    assert section_6.startswith("## 6. Authentication")
    assert "cabbage" in section_6


# ── main(): file generation, refusal to overwrite, --force ─────────────────

@pytest.fixture
def _redirected_paths(tmp_path, monkeypatch):
    variants_dir = tmp_path / "variants"
    ground_truth_path = tmp_path / "ground_truth.json"
    monkeypatch.setattr(mv, "VARIANTS_DIR", variants_dir)
    monkeypatch.setattr(mv, "GROUND_TRUTH_PATH", ground_truth_path)
    return variants_dir, ground_truth_path


def test_main_writes_all_variant_files_and_ground_truth(_redirected_paths, monkeypatch, capsys):
    variants_dir, ground_truth_path = _redirected_paths
    monkeypatch.setattr("sys.argv", ["make_variants.py"])

    mv.main()

    for variant in mv.VARIANTS:
        assert (variants_dir / f"{variant['id']}.md").exists()

    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    assert set(ground_truth.keys()) == {v["id"] for v in mv.VARIANTS}
    assert ground_truth["v00_base"]["expected_flagged"] == []
    assert ground_truth["v06_complexity"]["expected_flagged"] == [
        "val_unneeded_complexity", "val_decision_architecture_style",
    ]

    out = capsys.readouterr().out
    assert out.isascii()


def test_main_refuses_to_overwrite_without_force(_redirected_paths, monkeypatch, capsys):
    variants_dir, _ = _redirected_paths
    monkeypatch.setattr("sys.argv", ["make_variants.py"])
    mv.main()

    marker_path = variants_dir / "v00_base.md"
    marker_path.write_text("UNTOUCHED MARKER", encoding="utf-8")

    mv.main()  # run again, still no --force
    assert marker_path.read_text(encoding="utf-8") == "UNTOUCHED MARKER"
    out = capsys.readouterr().out
    assert "refused to overwrite" in out


def test_main_force_overwrites(_redirected_paths, monkeypatch):
    variants_dir, _ = _redirected_paths
    monkeypatch.setattr("sys.argv", ["make_variants.py"])
    mv.main()

    marker_path = variants_dir / "v00_base.md"
    marker_path.write_text("UNTOUCHED MARKER", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["make_variants.py", "--force"])
    mv.main()

    assert marker_path.read_text(encoding="utf-8") != "UNTOUCHED MARKER"
