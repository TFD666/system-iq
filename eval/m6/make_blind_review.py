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
import re
from pathlib import Path

HERE = Path(__file__).parent
RUNS_DIR = HERE / "runs"
BLIND_DIR = HERE / "blind"
BLIND_KEY_PATH = HERE / "blind_key.json"
RATINGS_PATH = BLIND_DIR / "ratings.csv"
REPORT_PATH = HERE / "report.md"

RATING_FIELDS = ("specific", "correct", "useful", "clear")

# Round 2 (three arms: A, B, B2) -- a separate file set from the round-1
# ones above, which stay untouched by everything below.
BLIND3_DIR = HERE / "blind3"
BLIND3_KEY_PATH = HERE / "blind3_key.json"
RATINGS3_PATH = BLIND3_DIR / "ratings.csv"
DEFAULT_ARMS = ("A", "B", "B2")
_XYZ_LABELS = ("X", "Y", "Z")

# Section 13 is code-built from the decisions, not written by the LLM --
# never shown in a blind review (it would give away which design is which).
_SECTION_13_RE = re.compile(r"\n?## 13\..*", re.DOTALL)


def _read_json_bom(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _strip_section_13(markdown: str) -> str:
    return _SECTION_13_RE.sub("", markdown).rstrip()


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
    for field in dict.fromkeys(RATING_FIELDS):  # each field printed once, even if listed twice
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
        design_x = _strip_section_13(_read_json_bom(result_paths[(idea, x_version)]).get("design_markdown") or "")
        design_y = _strip_section_13(_read_json_bom(result_paths[(idea, y_version)]).get("design_markdown") or "")

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
    for field in dict.fromkeys(RATING_FIELDS):  # each field printed once, even if listed twice
        a_val = averages["A"][field]
        b_val = averages["B"][field]
        a_str = f"{a_val:.2f}" if isinstance(a_val, float) else str(a_val)
        b_str = f"{b_val:.2f}" if isinstance(b_val, float) else str(b_val)
        lines.append(f"| {field} | {a_str} | {b_str} |")
    lines.append(f"| n | {averages['A']['n']} | {averages['B']['n']} |")
    lines.append("")

    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_path.write_text(existing + "\n".join(lines), encoding="utf-8")


def _rating_form_for(label: str) -> str:
    lines = [f"## Rating: Design {label} (1-5, 5 = best)", ""]
    for field in dict.fromkeys(RATING_FIELDS):  # each field printed once, even if listed twice
        lines.append(f"- {field}: ")
    return "\n".join(lines)


def build_three_way_assignments(
    ideas: list[str], arms: tuple[str, ...], seed: int,
) -> dict[str, dict[str, str]]:
    """{idea: {"X": arm, "Y": arm, "Z": arm}} -- a seeded random permutation
    of `arms` per idea, deterministic for a given seed."""
    rng = random.Random(seed)
    assignments = {}
    for idea in ideas:
        order = list(arms)
        rng.shuffle(order)
        assignments[idea] = dict(zip(_XYZ_LABELS, order))
    return assignments


def make_three_way_blind_reviews(
    seed: int = 11, arms: tuple[str, ...] = DEFAULT_ARMS,
    runs_dir: Path = RUNS_DIR, blind3_dir: Path = BLIND3_DIR,
    key_path: Path = BLIND3_KEY_PATH, force: bool = False,
) -> dict:
    """
    For every idea with an r1 run of EVERY arm in `arms`: writes
    blind3_dir/<idea>.md showing each arm's r1 design as Design X/Y/Z (a
    seeded random order per idea), section 13 stripped, with its own
    rating form. The key (idea -> {"X": arm, ...}) goes only into
    key_path, never into the review file. Refuses (FileExistsError) to
    overwrite an existing key_path or any *.md already in blind3_dir
    unless force=True.
    """
    if not force:
        clashes = []
        if key_path.exists():
            clashes.append(str(key_path.name))
        if blind3_dir.exists() and any(blind3_dir.glob("*.md")):
            clashes.append(f"{blind3_dir.name}/*.md")
        if clashes:
            raise FileExistsError(
                "refusing to overwrite existing blind3 output (" + ", ".join(clashes) + "); use force=True"
            )

    result_paths: dict[tuple, Path] = {}
    for meta_path in sorted(runs_dir.glob("*.meta.json")):
        meta = _read_json_bom(meta_path)
        if meta.get("repeat") != 1:
            continue
        run_id = meta_path.name[: -len(".meta.json")]
        result_path = runs_dir / f"{run_id}.json"
        if result_path.exists():
            result_paths[(meta["idea"], meta["version"])] = result_path

    ideas = sorted({idea for (idea, _v) in result_paths})
    ideas_with_all_arms = [idea for idea in ideas if all((idea, arm) in result_paths for arm in arms)]

    assignments = build_three_way_assignments(ideas_with_all_arms, arms, seed)
    key: dict[str, dict[str, str]] = {}
    blind3_dir.mkdir(parents=True, exist_ok=True)

    for idea in ideas_with_all_arms:
        labels = assignments[idea]
        parts = [f"# Blind review round 2 (three arms): {idea}"]
        for label in _XYZ_LABELS[:len(labels)]:
            arm = labels[label]
            design_text = _strip_section_13(
                _read_json_bom(result_paths[(idea, arm)]).get("design_markdown") or ""
            )
            parts.append(f"## Design {label}\n\n{design_text}")
            parts.append(_rating_form_for(label))
        (blind3_dir / f"{idea}.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        key[idea] = labels

    key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")
    return key


def reveal_three_way(
    arms: tuple[str, ...] = DEFAULT_ARMS,
    ratings_path: Path = RATINGS3_PATH, key_path: Path = BLIND3_KEY_PATH,
) -> dict:
    """
    Returns {"averages": {arm: {field: mean, "overall_mean": mean, "n": n}},
    "wins": {arm: count}, "ties": count}. "wins" is, per idea, which arm
    had the single highest overall (mean-of-fields) rating -- a tie for
    the top rating on an idea counts toward "ties" instead of any arm.
    """
    key = _read_json_bom(key_path)
    fields = list(dict.fromkeys(RATING_FIELDS))
    sums = {arm: {f: 0.0 for f in fields} for arm in arms}
    counts = {arm: 0 for arm in arms}
    per_idea_overall: dict[str, dict[str, float]] = {}

    with open(ratings_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            idea = row["idea"]
            design = row["design"]
            if idea not in key or design not in key[idea]:
                raise ValueError(f"{idea}: no key entry for design {design!r}")
            arm = key[idea][design]
            counts[arm] += 1
            values = [float(row[field]) for field in fields]
            for field, value in zip(fields, values):
                sums[arm][field] += value
            per_idea_overall.setdefault(idea, {})[arm] = sum(values) / len(values)

    averages = {}
    for arm in arms:
        n = counts[arm]
        field_means = {field: (sums[arm][field] / n) if n else "n/a" for field in fields}
        numeric_means = [v for v in field_means.values() if isinstance(v, float)]
        overall_mean = sum(numeric_means) / len(numeric_means) if numeric_means else "n/a"
        averages[arm] = {**field_means, "overall_mean": overall_mean, "n": n}

    wins = {arm: 0 for arm in arms}
    ties = 0
    for arm_means in per_idea_overall.values():
        if not arm_means:
            continue
        best = max(arm_means.values())
        winners = [arm for arm, m in arm_means.items() if m == best]
        if len(winners) == 1:
            wins[winners[0]] += 1
        else:
            ties += 1

    return {"averages": averages, "wins": wins, "ties": ties}


def _append_three_way_averages_to_report(
    result: dict, arms: tuple[str, ...] = DEFAULT_ARMS, report_path: Path = REPORT_PATH,
) -> None:
    averages = result["averages"]
    wins = result["wins"]
    fields = list(dict.fromkeys(RATING_FIELDS))

    def _fmt(value) -> str:
        return f"{value:.2f}" if isinstance(value, float) else str(value)

    lines = ["", "## Blind review round 2 (three arms)", ""]
    lines.append("| field | " + " | ".join(arms) + " |")
    lines.append("|---|" + "---|" * len(arms))
    for field in fields:
        lines.append(f"| {field} | " + " | ".join(_fmt(averages[arm][field]) for arm in arms) + " |")
    lines.append("| overall_mean | " + " | ".join(_fmt(averages[arm]["overall_mean"]) for arm in arms) + " |")
    lines.append("| n | " + " | ".join(str(averages[arm]["n"]) for arm in arms) + " |")
    lines.append(
        "| wins (highest overall_mean) | " + " | ".join(str(wins[arm]) for arm in arms) + " |"
    )
    lines.append(f"ties={result['ties']}")
    lines.append("")

    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    report_path.write_text(existing + "\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build (or reveal) the M6 blind design review(s).")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--reveal", action="store_true")
    parser.add_argument(
        "--three-way", action="store_true",
        help="Build/reveal the round-2 three-arm (blind3/) review instead of the round-1 one.",
    )
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS), help="Comma-separated arms for --three-way.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing blind3 output (three-way only).")
    args = parser.parse_args()

    if args.three_way:
        arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
        seed = args.seed if args.seed is not None else 11

        if args.reveal:
            result = reveal_three_way(arms=arms)
            _append_three_way_averages_to_report(result, arms=arms)
            print(f"appended three-way ratings to {REPORT_PATH.name}")
            for arm in arms:
                print(f"{arm}: n={result['averages'][arm]['n']} wins={result['wins'][arm]}")
            return

        try:
            key = make_three_way_blind_reviews(seed=seed, arms=arms, force=args.force)
        except FileExistsError as e:
            print(f"refused: {e}")
            return
        print(f"wrote {len(key)} three-way blind review file(s) to {BLIND3_DIR.name}/")
        print(f"wrote key: {BLIND3_KEY_PATH.name}")
        return

    seed = args.seed if args.seed is not None else 7

    if args.reveal:
        averages = reveal()
        _append_averages_to_report(averages)
        print(f"appended ratings to {REPORT_PATH.name}")
        for version in ("A", "B"):
            print(f"{version}: n={averages[version]['n']}")
        return

    key = make_blind_reviews(seed)
    print(f"wrote {len(key)} blind review file(s) to {BLIND_DIR.name}/")
    print(f"wrote key: {BLIND_KEY_PATH.name}")


if __name__ == "__main__":
    main()
