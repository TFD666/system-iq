"""
Score eval/m6/runs/*.json (version A = llm_only baseline, version B =
full pipeline) and write eval/m6/report.md. Standard library only
(plus an optional import from the backend for the placeholder/jargon
word lists and section headings -- falls back to local copies).

Every metric here is deterministic and keyword/structure based -- no
model is ever called to score a run. Reads both JSON kinds tolerant of
a leading UTF-8 BOM, and never prints design or idea text.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
RUNS_DIR = HERE / "runs"
DEFAULT_IDEAS_DIR = HERE.parent / "ideas"
REPORT_PATH = HERE / "report.md"

FALLBACK_LINE = "This section could not be generated."

try:
    sys.path.insert(0, str(HERE.parent.parent / "backend"))
    from app.design.checks import JARGON_TOKENS, PLACEHOLDER_PHRASES, split_into_sections
    from app.design.sections import all_headings
except Exception:
    PLACEHOLDER_PHRASES = ("tbd", "to be determined", "not finalized")
    JARGON_TOKENS = ("needs_review", "based_on_unknowns", "decision status")

    def all_headings() -> list[str]:
        return [f"## {n}. " for n in range(1, 14)]  # never hit when the import works

    def split_into_sections(markdown: str, headings: list[str]) -> dict:
        found = sorted((idx, h) for h in headings if (idx := markdown.find(h)) != -1)
        bodies: dict[str, str | None] = {h: None for h in headings}
        for pos, (start, h) in enumerate(found):
            body_start = start + len(h)
            body_end = found[pos + 1][0] if pos + 1 < len(found) else len(markdown)
            bodies[h] = markdown[body_start:body_end].strip()
        return bodies

TECH_CATEGORIES = {
    "api_style": ["REST", "GraphQL", "gRPC"],
    "database": ["PostgreSQL", "MySQL", "MongoDB", "DynamoDB", "SQLite", "Firebase"],
    "architecture": ["monolith", "microservices", "serverless", "modular monolith"],
}

_ATTACHED_UNITS = ("ms", "gb", "mb", "tb")
_WORD_UNITS = ("users", "requests", "rps", "percent")
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_ASSUMPTION_TOKENS = ("unspecified", "not specified", "not stated", "assum")


def _read_json_bom(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _read_text_bom(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def _is_real_run(version: str, meta: dict) -> bool:
    if version == "A":
        return bool(meta.get("llm_model")) and bool(meta.get("design_group_stats"))
    decision_model = str(meta.get("decision_model") or "").lower()
    validation_model = meta.get("validation_model")
    if "fake" in decision_model or "replay" in decision_model:
        return False
    if not validation_model or "fake" in str(validation_model).lower() or "replay" in str(validation_model).lower():
        return False
    if not meta.get("validation_input_tokens"):
        return False
    if meta.get("validation_status") == "skipped":
        return False
    return True


def _sections_1_12_text(markdown: str) -> str:
    headings = all_headings()
    bodies = split_into_sections(markdown, headings)
    return "\n".join(bodies.get(h) or "" for h in headings[:12])


def _numeric_claims(text: str) -> list[str]:
    claims = []
    for m in _NUMBER_RE.finditer(text):
        number = m.group(0)
        tail = text[m.end():m.end() + 20]
        if tail.startswith("%"):
            claims.append(number)
            continue
        attached = re.match(r"[a-zA-Z]+", tail.lower())
        if attached and attached.group(0) in _ATTACHED_UNITS:
            claims.append(number)
            continue
        following = " ".join(tail.split()[:3]).lower()
        if any(u in following for u in _WORD_UNITS) or "per second" in following:
            claims.append(number)
    return claims


def _number_is_supported(number: str, idea_text: str, requirements: dict) -> bool:
    normalized = number.replace(",", "")
    haystacks = [idea_text]
    scale = (requirements or {}).get("expected_scale") or {}
    haystacks.extend(str(v) for v in scale.values() if v is not None)
    for haystack in haystacks:
        cleaned = haystack.replace(",", "")
        if number in haystack or normalized in cleaned:
            return True
    return False


def _tech_choices(sections_text: str) -> dict:
    choices = {}
    for category, terms in TECH_CATEGORIES.items():
        counts = {
            term: len(re.findall(r"\b" + re.escape(term) + r"\b", sections_text, re.IGNORECASE))
            for term in terms
        }
        best = max(counts.values()) if counts else 0
        winners = [term for term, c in counts.items() if c == best]
        choices[category] = winners[0] if (best > 0 and len(winners) == 1) else "none"
    return choices


def _decision_adherence(decisions: list | None, markdown: str) -> float | str:
    if not decisions:
        return "n/a"
    accepted = [d for d in decisions if d.get("status") == "accepted" and d.get("choice")]
    if not accepted:
        return "n/a"
    markdown_lower = markdown.lower()
    hits = sum(1 for d in accepted if d["choice"].lower() in markdown_lower)
    return hits / len(accepted)


def _score_one_run(run_id: str, body: dict, meta_info: dict, idea_text: str) -> dict:
    version = meta_info["version"]
    markdown = body.get("design_markdown") or ""
    meta = body.get("meta") or {}
    headings = all_headings()

    sections_found = sum(1 for h in headings if h in markdown)
    fallback_lines = markdown.count(FALLBACK_LINE)
    design_warnings = len(body.get("design_warnings") or [])

    markdown_lower = markdown.lower()
    placeholder_hits = sum(markdown_lower.count(p) for p in PLACEHOLDER_PHRASES)
    jargon_hits = sum(markdown_lower.count(j) for j in JARGON_TOKENS)

    sections_text = _sections_1_12_text(markdown)
    sections_text_lower = sections_text.lower()

    claims = _numeric_claims(sections_text)
    unsupported_numbers = sum(
        1 for n in claims if not _number_is_supported(n, idea_text, body.get("requirements") or {})
    )

    assumption_mentions = sum(sections_text_lower.count(tok) for tok in _ASSUMPTION_TOKENS)

    tech_choices = _tech_choices(sections_text)

    group_stats = meta.get("design_group_stats") or []
    elapsed_seconds = sum(stat.get("elapsed_seconds") or 0 for stat in group_stats)

    if version == "B":
        decision_adherence = _decision_adherence(body.get("decisions"), markdown)
        jev_requests = 1 + (meta.get("validation_calls") or 0)
        jev_input_tokens = (meta.get("input_tokens") or 0) + (meta.get("validation_input_tokens") or 0)
        jev_output_tokens = (meta.get("output_tokens") or 0) + (meta.get("validation_output_tokens") or 0)
        validation = body.get("validation") or []
        flagged_ids = [v["id"] for v in validation if v.get("status") == "flagged"]
        possible_ids = [v["id"] for v in validation if v.get("status") == "possible"]
    else:
        decision_adherence = "n/a"
        jev_requests = 0
        jev_input_tokens = 0
        jev_output_tokens = 0
        flagged_ids = []
        possible_ids = []

    return {
        "run_id": run_id,
        "idea": meta_info["idea"],
        "version": version,
        "repeat": meta_info["repeat"],
        "sections_found": sections_found,
        "fallback_lines": fallback_lines,
        "design_warnings": design_warnings,
        "placeholder_hits": placeholder_hits,
        "jargon_hits": jargon_hits,
        "decision_adherence": decision_adherence,
        "tech_choices": tech_choices,
        "unsupported_numbers": unsupported_numbers,
        "assumption_mentions": assumption_mentions,
        "design_prompt_tokens": meta.get("design_prompt_tokens") or 0,
        "design_completion_tokens": meta.get("design_completion_tokens") or 0,
        "elapsed_seconds": elapsed_seconds,
        "jev_requests": jev_requests,
        "jev_input_tokens": jev_input_tokens,
        "jev_output_tokens": jev_output_tokens,
        "flagged_ids": flagged_ids,
        "possible_ids": possible_ids,
        "flagged_count": len(flagged_ids),
        "possible_count": len(possible_ids),
    }


_NUMERIC_METRIC_KEYS = (
    "sections_found", "fallback_lines", "design_warnings", "placeholder_hits", "jargon_hits",
    "unsupported_numbers", "assumption_mentions", "design_prompt_tokens", "design_completion_tokens",
    "elapsed_seconds", "jev_requests", "jev_input_tokens", "jev_output_tokens",
    "flagged_count", "possible_count",
)


def _mean(values: list) -> float | str:
    values = [v for v in values if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else "n/a"


def score(ideas_dir: Path = DEFAULT_IDEAS_DIR, runs_dir: Path = RUNS_DIR) -> dict:
    meta_paths = sorted(runs_dir.glob("*.meta.json"))
    runs: list[dict] = []
    ignored: list[str] = []
    for meta_path in meta_paths:
        run_id = meta_path.name[: -len(".meta.json")]
        result_path = runs_dir / f"{run_id}.json"
        if not result_path.exists():
            continue
        meta_info = _read_json_bom(meta_path)
        body = _read_json_bom(result_path)
        meta = body.get("meta") or {}
        if not _is_real_run(meta_info["version"], meta):
            ignored.append(run_id)
            continue
        idea_path = ideas_dir / f"{meta_info['idea']}.md"
        idea_text = _read_text_bom(idea_path) if idea_path.exists() else ""
        runs.append(_score_one_run(run_id, body, meta_info, idea_text))

    by_idea_version: dict[tuple, list[dict]] = {}
    for r in runs:
        by_idea_version.setdefault((r["idea"], r["version"]), []).append(r)

    aggregate = {"A": {}, "B": {}}
    for version in ("A", "B"):
        version_runs = [r for r in runs if r["version"] == version]
        aggregate[version]["n"] = len(version_runs)
        for key in _NUMERIC_METRIC_KEYS:
            aggregate[version][key] = _mean([r[key] for r in version_runs])
        adherence_values = [r["decision_adherence"] for r in version_runs if isinstance(r["decision_adherence"], (int, float))]
        aggregate[version]["decision_adherence"] = _mean(adherence_values) if adherence_values else "n/a"

    consistency = {}
    for (idea, version), group in sorted(by_idea_version.items()):
        if len(group) < 2:
            consistency[(idea, version)] = "n/a"
            continue
        agree = 0
        for category in TECH_CATEGORIES:
            values = {r["tech_choices"][category] for r in group}
            if len(values) == 1:
                agree += 1
        consistency[(idea, version)] = agree / len(TECH_CATEGORIES)

    ideas = sorted({r["idea"] for r in runs})

    return {
        "runs": runs,
        "ignored": ignored,
        "ideas": ideas,
        "by_idea_version": by_idea_version,
        "aggregate": aggregate,
        "consistency": consistency,
    }


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_report(data: dict) -> str:
    lines = [
        "# M6 eval report: version A (llm_only) vs version B (pipeline)",
        "",
        "Every metric below is computed deterministically by keyword/structure "
        "matching -- no model scored any of this.",
        "",
    ]

    if data["ignored"]:
        lines.append("Ignored (failed the real-run check): " + ", ".join(data["ignored"]))
        lines.append("")

    lines.append("## Per idea")
    lines.append("")
    for idea in data["ideas"]:
        lines.append(f"### {idea}")
        lines.append("")
        lines.append("| version | repeat | sections_found | fallback_lines | warnings | "
                      "placeholder_hits | jargon_hits | decision_adherence | unsupported_numbers | "
                      "assumption_mentions | tech_choices | jev_requests |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for version in ("A", "B"):
            for r in data["by_idea_version"].get((idea, version), []):
                tech = ", ".join(f"{k}={v}" for k, v in r["tech_choices"].items())
                lines.append(
                    f"| {r['version']} | {r['repeat']} | {r['sections_found']} | {r['fallback_lines']} | "
                    f"{r['design_warnings']} | {r['placeholder_hits']} | {r['jargon_hits']} | "
                    f"{_fmt(r['decision_adherence'])} | {r['unsupported_numbers']} | "
                    f"{r['assumption_mentions']} | {tech} | {r['jev_requests']} |"
                )
        lines.append("")

    lines.append("## Aggregate (mean, n shown)")
    lines.append("")
    lines.append("| metric | A | B |")
    lines.append("|---|---|---|")
    lines.append(f"| n | {data['aggregate']['A']['n']} | {data['aggregate']['B']['n']} |")
    for key in _NUMERIC_METRIC_KEYS:
        a_val = _fmt(data["aggregate"]["A"].get(key, "n/a"))
        b_val = _fmt(data["aggregate"]["B"].get(key, "n/a"))
        lines.append(f"| {key} | {a_val} | {b_val} |")
    lines.append(
        f"| decision_adherence | n/a | {_fmt(data['aggregate']['B'].get('decision_adherence', 'n/a'))} |"
    )
    lines.append("")

    lines.append("## Consistency across repeats (fraction of tech categories identical)")
    lines.append("")
    lines.append("| idea | version | consistency |")
    lines.append("|---|---|---|")
    for (idea, version), value in sorted(data["consistency"].items()):
        lines.append(f"| {idea} | {version} | {_fmt(value)} |")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append("- n is tiny (a handful of ideas, a handful of repeats each).")
    lines.append("- Metrics are crude keyword/structure counts, not a judgment of design quality.")
    lines.append("- Both versions use free-tier models behind one LLM and one decision provider.")
    lines.append("- This says how these two modes behaved on these specific ideas, not a general claim "
                  "about llm-only vs pipeline design quality.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    data = score()
    REPORT_PATH.write_text(render_report(data), encoding="utf-8")
    print(f"wrote: {REPORT_PATH.name}")
    print(f"runs scored: {len(data['runs'])}")
    if data["ignored"]:
        print("ignored (not a real run): " + ", ".join(data["ignored"]))
    else:
        print("ignored (not a real run): none")


if __name__ == "__main__":
    main()
