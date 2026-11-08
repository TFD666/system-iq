"""
Score eval/seeded/results/*.json against ground_truth.json and write
eval/seeded/report.md. Standard library only; reads both JSON kinds
tolerant of a leading UTF-8 BOM.

Two views of "predicted flagged":
  strict  -- status == "flagged"
  lenient -- status == "flagged" or "possible"
Both are scored per question id and overall, as TP/FN/FP/TN, with
precision/recall where the denominator isn't zero (else "n/a").
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
GROUND_TRUTH_PATH = HERE / "ground_truth.json"
RESULTS_DIR = HERE / "results"
REPORT_PATH = HERE / "report.md"

VIEWS = ("strict", "lenient")


def _read_json_bom(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _predicted_flagged(status: str, view: str) -> bool:
    if view == "strict":
        return status == "flagged"
    return status in ("flagged", "possible")


def _is_real_jev_result(meta: dict) -> bool:
    """
    decision_model is fixed to "n/a (validation only)" on /validate, so
    validation_model (plus a real token count) is what tells a real Jev
    run apart from a fake/replay provider or one that never ran.
    """
    model_label = str(meta.get("validation_model") or "").lower()
    if not model_label or "fake" in model_label or "replay" in model_label:
        return False
    return bool(meta.get("validation_input_tokens"))


def _empty_counts() -> dict:
    return {"TP": 0, "FN": 0, "FP": 0, "TN": 0}


def _precision_recall(counts: dict) -> tuple[str, str]:
    tp, fp, fn = counts["TP"], counts["FP"], counts["FN"]
    precision = f"{tp / (tp + fp):.2f}" if (tp + fp) else "n/a"
    recall = f"{tp / (tp + fn):.2f}" if (tp + fn) else "n/a"
    return precision, recall


def score() -> dict:
    """
    Returns a dict with everything report.md needs, so tests can check
    the numbers directly without parsing markdown.
    """
    ground_truth = _read_json_bom(GROUND_TRUTH_PATH)
    variant_ids = sorted(ground_truth.keys())

    results: dict[str, dict] = {}
    pending: list[str] = []
    ignored: list[str] = []
    for variant_id in variant_ids:
        path = RESULTS_DIR / f"{variant_id}.json"
        if not path.exists():
            pending.append(variant_id)
            continue
        body = _read_json_bom(path)
        if not _is_real_jev_result(body.get("meta") or {}):
            ignored.append(variant_id)
            continue
        results[variant_id] = body

    seen_question_ids: set[str] = set()
    for body in results.values():
        for entry in body.get("validation") or []:
            seen_question_ids.add(entry["id"])
    all_question_ids = sorted(seen_question_ids)

    # table[variant][qid] = {"status", "probability", "expected"}
    table: dict[str, dict[str, dict]] = {}
    missing_notes: list[str] = []
    per_question = {view: {} for view in VIEWS}
    overall = {view: _empty_counts() for view in VIEWS}
    misses: list[dict] = []       # strict-view false negatives
    false_positives: list[dict] = []  # strict-view false positives

    for variant_id in variant_ids:
        if variant_id not in results:
            continue
        expected_set = set(ground_truth[variant_id]["expected_flagged"])
        by_id = {entry["id"]: entry for entry in results[variant_id].get("validation") or []}
        table[variant_id] = {}

        for qid in all_question_ids:
            if qid not in by_id:
                missing_notes.append(f"{variant_id}: {qid} missing from result")
                continue

            entry = by_id[qid]
            status = entry["status"]
            probability = entry["probability"]
            expected = qid in expected_set
            table[variant_id][qid] = {
                "status": status, "probability": probability, "expected": expected,
            }

            for view in VIEWS:
                per_question[view].setdefault(qid, _empty_counts())
                predicted = _predicted_flagged(status, view)
                if expected and predicted:
                    key = "TP"
                elif expected and not predicted:
                    key = "FN"
                elif not expected and predicted:
                    key = "FP"
                else:
                    key = "TN"
                per_question[view][qid][key] += 1
                overall[view][key] += 1

            if expected and not _predicted_flagged(status, "strict"):
                misses.append({"variant": variant_id, "id": qid, "probability": probability})
            if not expected and _predicted_flagged(status, "strict"):
                false_positives.append({"variant": variant_id, "id": qid, "probability": probability})

    return {
        "variant_ids": variant_ids,
        "all_question_ids": all_question_ids,
        "table": table,
        "pending": pending,
        "ignored": ignored,
        "missing_notes": missing_notes,
        "per_question": per_question,
        "overall": overall,
        "misses": misses,
        "false_positives": false_positives,
    }


def _pct(p) -> str:
    return f"{p * 100:.0f}%" if isinstance(p, (int, float)) else "n/a"


def render_report(data: dict) -> str:
    lines = [
        "# Seeded design-validation report",
        "",
        "n is tiny (one base design, one project idea, 9 synthetic defects, hand-written). "
        "These numbers show how Jev behaves on these specific cases, not general accuracy.",
        "",
    ]

    if data["pending"]:
        lines.append("Pending variants (no result file yet): " + ", ".join(data["pending"]))
        lines.append("")

    if data["ignored"]:
        lines.append("Ignored (not a real Jev result): " + ", ".join(data["ignored"]))
        lines.append("")

    lines.append("## Variant by question")
    lines.append("")
    header = "| variant | " + " | ".join(data["all_question_ids"]) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(data["all_question_ids"]) + 1))
    for variant_id in data["variant_ids"]:
        if variant_id not in data["table"]:
            continue
        row = [variant_id]
        for qid in data["all_question_ids"]:
            cell = data["table"][variant_id].get(qid)
            if cell is None:
                row.append("-")
                continue
            mark = "E" if cell["expected"] else ""
            row.append(f"{cell['status']} {_pct(cell['probability'])}{mark}")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("(E marks a cell where this question was expected to be flagged.)")
    lines.append("")

    lines.append("## Per-question counts")
    lines.append("")
    for view in VIEWS:
        lines.append(f"### {view}")
        lines.append("")
        lines.append("| question | TP | FN | FP | TN | precision | recall |")
        lines.append("|---|---|---|---|---|---|---|")
        for qid in data["all_question_ids"]:
            counts = data["per_question"][view].get(qid, _empty_counts())
            precision, recall = _precision_recall(counts)
            lines.append(
                f"| {qid} | {counts['TP']} | {counts['FN']} | {counts['FP']} | "
                f"{counts['TN']} | {precision} | {recall} |"
            )
        lines.append("")

    lines.append("## Overall")
    lines.append("")
    for view in VIEWS:
        counts = data["overall"][view]
        precision, recall = _precision_recall(counts)
        lines.append(
            f"- {view}: TP={counts['TP']} FN={counts['FN']} FP={counts['FP']} "
            f"TN={counts['TN']} precision={precision} recall={recall}"
        )
    lines.append("")

    lines.append("## Misses (strict view: expected flagged, not predicted flagged)")
    lines.append("")
    if data["misses"]:
        for miss in data["misses"]:
            lines.append(f"- {miss['variant']}: {miss['id']} (probability {_pct(miss['probability'])})")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## False positives (strict view: not expected, but predicted flagged)")
    lines.append("")
    if data["false_positives"]:
        for fp in data["false_positives"]:
            lines.append(f"- {fp['variant']}: {fp['id']} (probability {_pct(fp['probability'])})")
    else:
        lines.append("- none")
    lines.append("")

    if data["missing_notes"]:
        lines.append("## Notes (question id missing from a result)")
        lines.append("")
        for note in data["missing_notes"]:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    data = score()
    REPORT_PATH.write_text(render_report(data), encoding="utf-8")
    print(f"wrote: {REPORT_PATH.name}")

    for view in VIEWS:
        counts = data["overall"][view]
        precision, recall = _precision_recall(counts)
        print(
            f"{view}: TP={counts['TP']} FN={counts['FN']} FP={counts['FP']} "
            f"TN={counts['TN']} precision={precision} recall={recall}"
        )

    if data["pending"]:
        print("pending: " + ", ".join(data["pending"]))
    else:
        print("pending: none")


if __name__ == "__main__":
    main()
