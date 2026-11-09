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

# category -> {term: [synonyms]}. "architecture" is handled specially
# (see _category_counts) because "modular monolith" must never also add
# to plain "monolith". Redis is deliberately not a database term here.
_API_STYLE_TERMS = {"REST": ["REST", "RESTful"], "GraphQL": ["GraphQL"], "gRPC": ["gRPC"]}
_DATABASE_TERMS = {
    "PostgreSQL": ["PostgreSQL", "Postgres", "PostGIS"],
    "MySQL": ["MySQL"],
    "MongoDB": ["MongoDB", "Mongo"],
    "DynamoDB": ["DynamoDB", "Dynamo"],
    "SQLite": ["SQLite"],
    "Firebase": ["Firebase"],
}
TECH_CATEGORIES = ("api_style", "database", "architecture")
# Each category is detected in its own section(s) first; if nothing is
# mentioned there, score() falls back to the full sections 1-12 text.
_CATEGORY_SECTIONS = {"architecture": (1, 2), "api_style": (4,), "database": (5,)}

_ATTACHED_UNITS = ("ms", "gb", "mb", "tb")
_WORD_UNITS = (
    "users", "requests", "rps", "seconds", "percent",
    "sellers", "patients", "members", "sensors", "doctors", "devices", "rows", "items",
)
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion",
)
_WRITTEN_NUMBER_RE = re.compile(
    r"\b(?:" + "|".join(_NUMBER_WORDS) + r")(?:[\s-](?:" + "|".join(_NUMBER_WORDS) + r"))*\b",
    re.IGNORECASE,
)
_ASSUMPTION_TOKENS = ("unspecified", "not specified", "not stated", "assum")
_LEAK_PHRASES = ("decisions are provided", "no decisions", "decisions were provided")


def _retry_reason_counts(group_stats: list) -> dict:
    counts: dict[str, int] = {}
    for stat in group_stats:
        for reason in stat.get("retry_reasons") or []:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


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


def _section_numbers_text(markdown: str, numbers: tuple[int, ...]) -> str:
    headings = all_headings()
    bodies = split_into_sections(markdown, headings)
    return "\n".join(bodies.get(headings[n - 1]) or "" for n in numbers)


def _find_unit_nearby(tail: str) -> str | None:
    """Returns the specific unit word/symbol found near a number, or None."""
    if tail.startswith("%"):
        return "%"
    attached = re.match(r"[a-zA-Z]+", tail.lower())
    if attached and attached.group(0) in _ATTACHED_UNITS:
        return attached.group(0)
    following = " ".join(tail.split()[:3]).lower()
    if "per second" in following:
        return "per second"
    for unit in _WORD_UNITS:
        if unit in following:
            return unit
    return None


def _context_snippet(text: str, start: int, end: int, n: int = 4) -> str:
    """Up to `n` words of design text on each side of text[start:end]."""
    before = " ".join(text[:start].split()[-n:])
    after = " ".join(text[end:].split()[:n])
    return f"{before} {text[start:end]} {after}".strip()


def _numeric_claims(text: str) -> list[dict]:
    """
    Every number (digits or spelled out, e.g. "ten thousand") followed
    within ~3 words by a unit word -- a numeric claim, not yet checked
    against the idea/requirements for support. Each claim carries its
    matched unit and a snippet of surrounding design text (no idea text).
    """
    claims = []
    for pattern in (_NUMBER_RE, _WRITTEN_NUMBER_RE):
        for m in pattern.finditer(text):
            unit = _find_unit_nearby(text[m.end():m.end() + 20])
            if unit is not None:
                claims.append({
                    "number": m.group(0),
                    "unit": unit,
                    "context": _context_snippet(text, m.start(), m.end()),
                })
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


def _term_count(synonyms: list[str], text: str) -> int:
    return sum(len(re.findall(r"\b" + re.escape(syn) + r"\b", text, re.IGNORECASE)) for syn in synonyms)


def _term_first_position(synonyms: list[str], text: str) -> int | None:
    positions = [m.start() for syn in synonyms if (m := re.search(r"\b" + re.escape(syn) + r"\b", text, re.IGNORECASE))]
    return min(positions) if positions else None


def _category_counts_and_positions(category: str, text: str) -> tuple[dict[str, int], dict[str, int | None]]:
    """Returns (counts, first-match char offset) per term in `text`."""
    if category == "architecture":
        modular_matches = list(re.finditer(r"\bmodular\s+monolith\b", text, re.IGNORECASE))
        monolith_pos = None
        monolith_count = 0
        for m in re.finditer(r"\bmonolith\b", text, re.IGNORECASE):
            if re.search(r"modular\s*$", text[:m.start()], re.IGNORECASE):
                continue  # part of "modular monolith" -- never double-counted
            monolith_count += 1
            if monolith_pos is None:
                monolith_pos = m.start()
        micro_matches = list(re.finditer(r"\bmicroservices?\b", text, re.IGNORECASE))
        serverless_matches = list(re.finditer(r"\bserverless\b", text, re.IGNORECASE))
        counts = {
            "modular monolith": len(modular_matches),
            "monolith": monolith_count,
            "microservices": len(micro_matches),
            "serverless": len(serverless_matches),
        }
        positions = {
            "modular monolith": modular_matches[0].start() if modular_matches else None,
            "monolith": monolith_pos,
            "microservices": micro_matches[0].start() if micro_matches else None,
            "serverless": serverless_matches[0].start() if serverless_matches else None,
        }
        return counts, positions

    synonyms_by_term = _API_STYLE_TERMS if category == "api_style" else _DATABASE_TERMS
    counts = {term: _term_count(syns, text) for term, syns in synonyms_by_term.items()}
    positions = {term: _term_first_position(syns, text) for term, syns in synonyms_by_term.items()}
    return counts, positions


def _pick_winner(counts: dict[str, int], positions: dict[str, int | None]) -> str:
    best = max(counts.values()) if counts else 0
    if best == 0:
        return "none"
    winners = [term for term, c in counts.items() if c == best]
    if len(winners) == 1:
        return winners[0]
    # A real tie: break it by whichever tied term was mentioned first.
    tied_positions: dict[str, int] = {t: p for t in winners if (p := positions.get(t)) is not None}
    if not tied_positions:
        return "mixed"
    return min(tied_positions, key=lambda t: tied_positions[t])


def _tech_choices(markdown: str) -> tuple[dict, dict, dict]:
    """
    Returns (choices, counts, scope) per category: the winning term (or
    "mixed"/"none"), the raw per-term counts, and which text the winner
    came from -- the category's own section(s), or a fallback to the full
    sections 1-12 text when its own section(s) had no mention at all.
    """
    choices: dict[str, str] = {}
    counts_by_category: dict[str, dict[str, int]] = {}
    scope_by_category: dict[str, str] = {}
    for category in TECH_CATEGORIES:
        designated_text = _section_numbers_text(markdown, _CATEGORY_SECTIONS[category])
        counts, positions = _category_counts_and_positions(category, designated_text)
        scope = "designated"
        if not any(counts.values()):
            scope = "fallback (1-12)"
            counts, positions = _category_counts_and_positions(category, _sections_1_12_text(markdown))
        choices[category] = _pick_winner(counts, positions)
        counts_by_category[category] = counts
        scope_by_category[category] = scope
    return choices, counts_by_category, scope_by_category


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
    numeric_claims = len(claims)
    requirements = body.get("requirements") or {}
    unsupported_listing = [
        {"number": c["number"], "unit": c["unit"], "context": c["context"]}
        for c in claims if not _number_is_supported(c["number"], idea_text, requirements)
    ]
    unsupported_numbers = len(unsupported_listing)

    assumption_mentions = sum(sections_text_lower.count(tok) for tok in _ASSUMPTION_TOKENS)
    leak_hits = sum(sections_text_lower.count(p) for p in _LEAK_PHRASES)

    tech_choices, tech_counts, tech_scope = _tech_choices(markdown)

    group_stats = meta.get("design_group_stats") or []
    elapsed_seconds = sum(stat.get("elapsed_seconds") or 0 for stat in group_stats)
    retries = sum(stat.get("retries") or 0 for stat in group_stats)
    retry_reason_counts = _retry_reason_counts(group_stats)

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
        "tech_counts": tech_counts,
        "tech_scope": tech_scope,
        "numeric_claims": numeric_claims,
        "unsupported_numbers": unsupported_numbers,
        "unsupported_listing": unsupported_listing,
        "assumption_mentions": assumption_mentions,
        "leak_hits": leak_hits,
        "retries": retries,
        "retry_reason_counts": retry_reason_counts,
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
    "numeric_claims", "unsupported_numbers", "assumption_mentions", "leak_hits", "retries",
    "design_prompt_tokens", "design_completion_tokens",
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

        retry_reason_totals: dict[str, int] = {}
        for r in version_runs:
            for category, count in r["retry_reason_counts"].items():
                retry_reason_totals[category] = retry_reason_totals.get(category, 0) + count
        aggregate[version]["retry_reason_totals"] = retry_reason_totals

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
    lines.append("(d) = detected in the category's own designated section(s); "
                  "(f) = no mention there, fell back to sections 1-12.")
    lines.append("")
    for idea in data["ideas"]:
        lines.append(f"### {idea}")
        lines.append("")
        lines.append("| version | repeat | sections_found | fallback_lines | warnings | "
                      "placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | "
                      "numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | "
                      "tech_counts | jev_requests |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for version in ("A", "B"):
            for r in data["by_idea_version"].get((idea, version), []):
                scope_abbrev = {"designated": "d", "fallback (1-12)": "f"}
                tech = ", ".join(
                    f"{k}={v}({scope_abbrev.get(r['tech_scope'][k], '?')})"
                    for k, v in r["tech_choices"].items()
                )
                tech_counts = "; ".join(
                    ",".join(f"{term}={c}" for term, c in counts.items() if c > 0) or "-"
                    for counts in r["tech_counts"].values()
                )
                lines.append(
                    f"| {r['version']} | {r['repeat']} | {r['sections_found']} | {r['fallback_lines']} | "
                    f"{r['design_warnings']} | {r['placeholder_hits']} | {r['jargon_hits']} | "
                    f"{r['leak_hits']} | {r['retries']} | {_fmt(r['decision_adherence'])} | "
                    f"{r['numeric_claims']} | {r['unsupported_numbers']} | {r['assumption_mentions']} | "
                    f"{tech} | {tech_counts} | {r['jev_requests']} |"
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

    lines.append("## Retry reasons (sum per category)")
    lines.append("")
    all_categories = sorted(
        set(data["aggregate"]["A"]["retry_reason_totals"]) | set(data["aggregate"]["B"]["retry_reason_totals"])
    )
    if not all_categories:
        lines.append("No retries were recorded.")
    else:
        lines.append("| category | A | B |")
        lines.append("|---|---|---|")
        for category in all_categories:
            a_total = data["aggregate"]["A"]["retry_reason_totals"].get(category, 0)
            b_total = data["aggregate"]["B"]["retry_reason_totals"].get(category, 0)
            lines.append(f"| {category} | {a_total} | {b_total} |")
    lines.append("")

    lines.append("## Unsupported numbers")
    lines.append("")
    lines.append("For every run, each numeric claim whose number never appears in the idea "
                  "text or the requirements' scale fields. Context is design text only.")
    lines.append("")
    any_unsupported = False
    for r in data["runs"]:
        if not r["unsupported_listing"]:
            continue
        any_unsupported = True
        lines.append(f"### {r['run_id']}")
        lines.append("")
        for claim in r["unsupported_listing"]:
            lines.append(f"- {claim['number']} ({claim['unit']}): \"{claim['context']}\"")
        lines.append("")
    if not any_unsupported:
        lines.append("none")
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
