"""
For every idea that has both an A and a B run, write a blind-review file
showing both designs as "Design X" / "Design Y" in a random (but seeded,
reproducible) order, plus a short 1-5 rating form. The key mapping X/Y
back to A/B goes only into blind_key.json -- never into the review file
itself, so a reviewer can't tell which is which.

With --reveal: read blind/ratings.csv, map X/Y back to A/B via the key,
and append the per-version averages to eval/m6/report.md.

Standard library only. Never prints design or idea text.
"""

import argparse
import csv
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
RUNS_DIR = HERE / "runs"
BLIND_DIR = HERE / "blind"
BLIND_KEY_PATH = HERE / "blind_key.json"
RATINGS_PATH = BLIND_DIR / "ratings.csv"
REPORT_PATH = HERE / "report.md"

RATING_FIELDS = ("specific", "correct", "useful", "clear")


def _read_json_bom(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def build_review_assignments(ideas: list[str], seed: int) -> dict[str, str]:
    """{idea: "AX"|"AY"} meaning which real version (A or B) is labeled X for
    that idea -- the other one is Y. Deterministic for a given seed."""
    rng = random.Random(seed)
    assignments = {}
    for idea in ideas:
        assignments[idea] = rng.choice(["A", "B"])  # the version shown as "Design X"
    return assignments


def _rating_form() -> str:
    lines = ["## Rating (1-5, 5 = best)", ""]
    for field in RATING_FIELDS:
        lines.append(f"- {field}: ")
    return "\n".join(lines)


def make_blind_reviews(
    seed: int, runs_dir: Path = RUNS_DIR, blind_dir: Path = BLIND_DIR, key_path: Path = BLIND_KEY_PATH,
) -> dict:
    result_paths: dict[tuple, Path] = {}
    for meta_path in sorted(runs_dir.glob("*.meta.json")):
        meta = _read_json_bom(meta_path)
        run_id = meta_path.name[: -len(".meta.json")]
        result_path = runs_dir / f"{run_id}.json"
        if result_path.exists():
            result_paths[(meta["idea"], meta["version"])] = result_path

    ideas = sorted({idea for (idea, _v) in result_paths})
    ideas_with_both = [idea for idea in ideas if (idea, "A") in result_paths and (idea, "B") in result_paths]

    x_is_version = build_review_assignments(ideas_with_both, seed)
    key = {}
    blind_dir.mkdir(parents=True, exist_ok=True)

    for idea in ideas_with_both:
        x_version = x_is_version[idea]
        y_version = "B" if x_version == "A" else "A"
        design_x = _read_json_bom(result_paths[(idea, x_version)]).get("design_markdown") or ""
        design_y = _read_json_bom(result_paths[(idea, y_version)]).get("design_markdown") or ""

        content = (
            f"# Blind review: {idea}\n\n"
            f"## Design X\n\n{design_x}\n\n"
            f"## Design Y\n\n{design_y}\n\n"
            f"{_rating_form()}\n"
        )
        (blind_dir / f"{idea}.md").write_text(content, encoding="utf-8")
        key[idea] = {"X": x_version, "Y": y_version}

    key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")
    return key


def reveal(ratings_path: Path = RATINGS_PATH, key_path: Path = BLIND_KEY_PATH) -> dict:
    """Returns {"A": {field: mean}, "B": {field: mean}} from ratings.csv,
    mapped back through the key. Raises ValueError on a bad key reference."""
    key = _read_json_bom(key_path)
    sums = {"A": {f: 0.0 for f in RATING_FIELDS}, "B": {f: 0.0 for f in RATING_FIELDS}}
    counts = {"A": 0, "B": 0}

    with open(ratings_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            idea = row["idea"]
            design = row["design"]
            if idea not in key or design not in key[idea]:
                raise ValueError(f"{idea}: no key entry for design {design!r}")
            version = key[idea][design]
            counts[version] += 1
            for field in RATING_FIELDS:
                sums[version][field] += float(row[field])

    averages = {"A": {}, "B": {}}
    for version in ("A", "B"):
        n = counts[version]
        for field in RATING_FIELDS:
            averages[version][field] = (sums[version][field] / n) if n else "n/a"
        averages[version]["n"] = n
    return averages


def _append_averages_to_report(averages: dict, report_path: Path = REPORT_PATH) -> None:
    lines = ["", "## Blind review ratings (revealed)", ""]
    lines.append("| field | A | B |")
    lines.append("|---|---|---|")
    for field in RATING_FIELDS:
        a_val = averages["A"][field]
        b_val = averages["B"][field]
        a_str = f"{a_val:.2f}" if isinstance(a_val, float) else str(a_val)
        b_str = f"{b_val:.2f}" if isinstance(b_val, float) else str(b_val)
        lines.append(f"| {field} | {a_str} | {b_str} |")
    lines.append(f"| n | {averages['A']['n']} | {averages['B']['n']} |")
    lines.append("")

    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_path.write_text(existing + "\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build (or reveal) the M6 blind design review.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reveal", action="store_true")
    args = parser.parse_args()

    if args.reveal:
        averages = reveal()
        _append_averages_to_report(averages)
        print(f"appended ratings to {REPORT_PATH.name}")
        for version in ("A", "B"):
            print(f"{version}: n={averages[version]['n']}")
        return

    key = make_blind_reviews(args.seed)
    print(f"wrote {len(key)} blind review file(s) to {BLIND_DIR.name}/")
    print(f"wrote key: {BLIND_KEY_PATH.name}")


if __name__ == "__main__":
    main()
