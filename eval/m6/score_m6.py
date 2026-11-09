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
# Words that make a following number NOT a quantity claim (a count of
# document structure, not of real-world things).
_IGNORED_FOLLOWING_WORDS = (
    "entities", "entity", "steps", "step", "sections", "section", "tables", "table",
    "fields", "field", "endpoints", "endpoint", "components", "component", "modules", "module",
    "layers", "layer",
)
# A number right after one of these is a version/crypto/protocol label,
# not a quantity (SHA-256, TLS 1.2, HTTP/2, v2, RS256, ...).
_IGNORED_PRECEDING_WORDS = (
    "sha", "hmac", "tls", "http", "oauth", "rs", "es", "aes", "v", "version",
)
_IGNORED_PRECEDING_RE = re.compile(r"([A-Za-z]+)[/\-]?\s*$")

_NUMBER_RE = re.compile(
    r"\d[\d,]*\.?\d*[kK]?(?:\s+(?:hundred|thousand|million|billion))?", re.IGNORECASE,
)
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMBER_WORDS = tuple(_ONES) + tuple(_TENS) + tuple(_SCALES)
_WRITTEN_NUMBER_RE = re.compile(
    r"\b(?:" + "|".join(_NUMBER_WORDS) + r")(?:[\s-](?:" + "|".join(_NUMBER_WORDS) + r"))*\b",
    re.IGNORECASE,
)
_ASSUMPTION_TOKENS = ("unspecified", "not specified", "not stated", "assum")
_LEAK_PHRASES = ("decisions are provided", "no decisions", "decisions were provided")

# A mention in a sentence containing any of these means the tech was
# rejected/compared, not chosen -- never counted toward tech_choices.
_NEGATION_PHRASES = (
    "avoid", "avoids", "instead of", "rather than", "not", "without", "over",
    "versus", "vs", "unlike", "no need for", "rejected", "considered but", "ruled out",
)
_NEGATION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in _NEGATION_PHRASES) + r")\b", re.IGNORECASE,
)

# decision.id -> which section(s) are that decision's own, for
# decision_adherence_in_designated_section (api_style 4, database 5,
# architecture 1 or 2 -- only decisions that map to a TECH_CATEGORIES slot).
_DECISION_DESIGNATED_SECTIONS = {
    "api_style": (4,),
    "primary_database": (5,),
    "architecture_style": (1, 2),
}


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


def _digits_to_int(token: str) -> int | None:
    """"500" -> 500, "10,000" -> 10000, "10k" -> 10000, "10 million" -> 10000000."""
    token = token.strip()
    scale = 1
    lowered = token.lower()
    for word, mult in _SCALES.items():
        if lowered.endswith(word):
            scale = mult
            token = token[: -len(word)].strip()
            break
    multiplier = 1
    if token[-1:].lower() == "k":
        multiplier = 1000
        token = token[:-1]
    cleaned = token.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return int(value * multiplier * scale)


def _words_to_int(phrase: str) -> int | None:
    """"ten thousand" -> 10000, "fifty" -> 50. None if not a pure number phrase."""
    total = 0
    current = 0
    found = False
    for word in re.split(r"[\s-]+", phrase.lower()):
        if word in _ONES:
            current += _ONES[word]
            found = True
        elif word in _TENS:
            current += _TENS[word]
            found = True
        elif word == "hundred":
            current = (current or 1) * 100
            found = True
        elif word in ("thousand", "million", "billion"):
            total += (current or 1) * _SCALES[word]
            current = 0
            found = True
        else:
            return None
    return total + current if found else None


def _is_ignored_by_preceding_word(text: str, start: int) -> bool:
    """True when the number is really a version/crypto/protocol label, e.g.
    SHA-256, TLS 1.2, HTTP/2, v2, RS256 -- not a quantity."""
    m = _IGNORED_PRECEDING_RE.search(text[:start])
    return bool(m and m.group(1).lower() in _IGNORED_PRECEDING_WORDS)


def _clean_word(word: str) -> str:
    return word.strip(".,;:()").lower()


def _classify_following(words_after: list[str]) -> tuple[str | None, bool]:
    """
    Scans the next word, then (if that one wasn't decisive) one more --
    "allow one adjective between" -- for either a unit word (returned) or
    a word that means this number isn't a quantity at all (ignored=True).
    """
    for i in range(min(2, len(words_after))):
        word = _clean_word(words_after[i])
        if word in _IGNORED_FOLLOWING_WORDS:
            return None, True
        if word in _WORD_UNITS:
            return word, False
        if word == "per" and i + 1 < len(words_after) and _clean_word(words_after[i + 1]) == "second":
            return "per second", False
    return None, False


def _context_snippet(text: str, start: int, end: int, n: int = 4) -> str:
    """Up to `n` words of design text on each side of text[start:end]."""
    before = " ".join(text[:start].split()[-n:])
    after = " ".join(text[end:].split()[:n])
    return f"{before} {text[start:end]} {after}".strip()


def _numeric_claims(text: str) -> list[dict]:
    """
    Every number (digits, "10k", or spelled out like "ten thousand")
    whose very next word (one adjective may sit in between, e.g. "50
    active users") is a unit word -- a numeric claim, not yet checked for
    support. Ignores version/protocol numbers (SHA-256, HTTP/2, v2, ...)
    and counts of document structure (steps, sections, entities, ...).
    Each claim carries its canonical integer value, matched unit, and a
    snippet of surrounding design text (no idea text).
    """
    claims = []
    digit_spans: list[tuple[int, int]] = []
    for pattern, to_int in ((_NUMBER_RE, _digits_to_int), (_WRITTEN_NUMBER_RE, _words_to_int)):
        for m in pattern.finditer(text):
            if pattern is _WRITTEN_NUMBER_RE and any(s <= m.start() < e for s, e in digit_spans):
                continue  # already captured as part of a digit+scale-word match, e.g. "10 million"
            if _is_ignored_by_preceding_word(text, m.start()):
                continue
            value = to_int(m.group(0))
            if value is None:
                continue
            if pattern is _NUMBER_RE:
                digit_spans.append((m.start(), m.end()))

            tail = text[m.end():m.end() + 2]
            if tail.startswith("%"):
                unit, end = "%", m.end() + 1
            else:
                attached = re.match(r"[a-zA-Z]+", text[m.end():m.end() + 4].lower())
                if attached and attached.group(0) in _ATTACHED_UNITS:
                    unit, end = attached.group(0), m.end() + len(attached.group(0))
                else:
                    words_after = text[m.end():m.end() + 60].split()
                    unit, ignored = _classify_following(words_after)
                    if ignored:
                        continue
                    end = m.end()

            if unit is None:
                continue

            claims.append({
                "number": m.group(0),
                "value": value,
                "unit": unit,
                "context": _context_snippet(text, m.start(), end),
            })
    return claims


def _number_is_supported(value: int, idea_text: str, requirements: dict) -> bool:
    haystacks = [idea_text]
    scale = (requirements or {}).get("expected_scale") or {}
    haystacks.extend(str(v) for v in scale.values() if v is not None)
    for haystack in haystacks:
        found = set()
        for m in _NUMBER_RE.finditer(haystack):
            v = _digits_to_int(m.group(0))
            if v is not None:
                found.add(v)
        for m in _WRITTEN_NUMBER_RE.finditer(haystack):
            v = _words_to_int(m.group(0))
            if v is not None:
                found.add(v)
        if value in found:
            return True
    return False


def _sentence_around(text: str, pos: int) -> str:
    """The sentence (bounded by . ! ? or newline) containing char offset pos."""
    left = max((text.rfind(ch, 0, pos) for ch in ".!?\n"), default=-1) + 1
    right_candidates = [c for ch in ".!?\n" if (c := text.find(ch, pos)) != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right]


def _is_negated_mention(text: str, pos: int) -> bool:
    """True when the sentence containing this match rejects/compares the
    tech rather than choosing it (e.g. "avoids microservices")."""
    return bool(_NEGATION_RE.search(_sentence_around(text, pos)))


def _finditer_excluding_negated(pattern: str, text: str) -> tuple[list[re.Match], int]:
    """(non-negated matches, count of matches excluded as negated)."""
    matches = []
    ignored = 0
    for m in re.finditer(pattern, text, re.IGNORECASE):
        if _is_negated_mention(text, m.start()):
            ignored += 1
        else:
            matches.append(m)
    return matches, ignored


def _term_count(synonyms: list[str], text: str) -> tuple[int, int]:
    """(effective count, ignored-as-negated count) across all synonyms."""
    count = 0
    ignored = 0
    for syn in synonyms:
        matches, syn_ignored = _finditer_excluding_negated(r"\b" + re.escape(syn) + r"\b", text)
        count += len(matches)
        ignored += syn_ignored
    return count, ignored


def _term_first_position(synonyms: list[str], text: str) -> int | None:
    positions = []
    for syn in synonyms:
        matches, _ignored = _finditer_excluding_negated(r"\b" + re.escape(syn) + r"\b", text)
        positions.extend(m.start() for m in matches)
    return min(positions) if positions else None


def _category_counts_and_positions(
    category: str, text: str,
) -> tuple[dict[str, int], dict[str, int | None], dict[str, int]]:
    """Returns (counts, first-match char offset, ignored-as-negated counts)
    per term in `text`. Counts never include a negated mention (e.g.
    "avoids microservices")."""
    if category == "architecture":
        modular_matches, modular_ignored = _finditer_excluding_negated(r"\bmodular\s+monolith\b", text)
        monolith_pos = None
        monolith_count = 0
        monolith_ignored = 0
        for m in re.finditer(r"\bmonolith\b", text, re.IGNORECASE):
            if re.search(r"modular\s*$", text[:m.start()], re.IGNORECASE):
                continue  # part of "modular monolith" -- never double-counted
            if _is_negated_mention(text, m.start()):
                monolith_ignored += 1
                continue
            monolith_count += 1
            if monolith_pos is None:
                monolith_pos = m.start()
        micro_matches, micro_ignored = _finditer_excluding_negated(r"\bmicroservices?\b", text)
        serverless_matches, serverless_ignored = _finditer_excluding_negated(r"\bserverless\b", text)
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
        ignored_counts = {
            "modular monolith": modular_ignored,
            "monolith": monolith_ignored,
            "microservices": micro_ignored,
            "serverless": serverless_ignored,
        }
        return counts, positions, ignored_counts

    synonyms_by_term = _API_STYLE_TERMS if category == "api_style" else _DATABASE_TERMS
    counts: dict[str, int] = {}
    ignored_counts: dict[str, int] = {}
    for term, syns in synonyms_by_term.items():
        counts[term], ignored_counts[term] = _term_count(syns, text)
    positions = {term: _term_first_position(syns, text) for term, syns in synonyms_by_term.items()}
    return counts, positions, ignored_counts


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


def _tech_choices(markdown: str) -> tuple[dict, dict, dict, dict]:
    """
    Returns (choices, counts, scope, ignored) per category: the winning term
    (or "mixed"/"none"), the per-term counts (negated mentions like "avoids
    microservices" excluded), which text the winner came from -- the
    category's own section(s), or a fallback to the full sections 1-12 text
    when its own section(s) had no mention at all -- and how many mentions
    per term were excluded as negated.
    """
    choices: dict[str, str] = {}
    counts_by_category: dict[str, dict[str, int]] = {}
    scope_by_category: dict[str, str] = {}
    ignored_by_category: dict[str, dict[str, int]] = {}
    for category in TECH_CATEGORIES:
        designated_text = _section_numbers_text(markdown, _CATEGORY_SECTIONS[category])
        counts, positions, ignored = _category_counts_and_positions(category, designated_text)
        scope = "designated"
        if not any(counts.values()):
            scope = "fallback (1-12)"
            counts, positions, ignored = _category_counts_and_positions(category, _sections_1_12_text(markdown))
        choices[category] = _pick_winner(counts, positions)
        counts_by_category[category] = counts
        scope_by_category[category] = scope
        ignored_by_category[category] = ignored
    return choices, counts_by_category, scope_by_category, ignored_by_category


def _decision_adherence(decisions: list | None, markdown: str) -> tuple[float | str, float | str]:
    """Returns (adherence, adherence_in_designated_section). Both are
    computed over sections 1-12 only -- section 13 is code-generated from
    the decisions and would pass by construction."""
    if not decisions:
        return "n/a", "n/a"
    accepted = [d for d in decisions if d.get("status") == "accepted" and d.get("choice")]
    if not accepted:
        return "n/a", "n/a"

    sections_1_12 = _sections_1_12_text(markdown).lower()
    hits = sum(1 for d in accepted if d["choice"].lower() in sections_1_12)
    adherence = hits / len(accepted)

    designated = [d for d in accepted if d["id"] in _DECISION_DESIGNATED_SECTIONS]
    if not designated:
        return adherence, "n/a"
    designated_hits = sum(
        1 for d in designated
        if d["choice"].lower() in _section_numbers_text(markdown, _DECISION_DESIGNATED_SECTIONS[d["id"]]).lower()
    )
    return adherence, designated_hits / len(designated)


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
        for c in claims if not _number_is_supported(c["value"], idea_text, requirements)
    ]
    unsupported_numbers = len(unsupported_listing)

    assumption_mentions = sum(sections_text_lower.count(tok) for tok in _ASSUMPTION_TOKENS)
    leak_hits = sum(sections_text_lower.count(p) for p in _LEAK_PHRASES)

    tech_choices, tech_counts, tech_scope, tech_ignored = _tech_choices(markdown)

    group_stats = meta.get("design_group_stats") or []
    elapsed_seconds = sum(stat.get("elapsed_seconds") or 0 for stat in group_stats)
    retries = sum(stat.get("retries") or 0 for stat in group_stats)
    retry_reason_counts = _retry_reason_counts(group_stats)

    if version == "B":
        decision_adherence, decision_adherence_in_designated_section = _decision_adherence(
            body.get("decisions"), markdown,
        )
        jev_requests = 1 + (meta.get("validation_calls") or 0)
        jev_input_tokens = (meta.get("input_tokens") or 0) + (meta.get("validation_input_tokens") or 0)
        jev_output_tokens = (meta.get("output_tokens") or 0) + (meta.get("validation_output_tokens") or 0)
        validation = body.get("validation") or []
        flagged_ids = [v["id"] for v in validation if v.get("status") == "flagged"]
        possible_ids = [v["id"] for v in validation if v.get("status") == "possible"]
    else:
        decision_adherence = "n/a"
        decision_adherence_in_designated_section = "n/a"
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
        "decision_adherence_in_designated_section": decision_adherence_in_designated_section,
        "tech_choices": tech_choices,
        "tech_counts": tech_counts,
        "tech_scope": tech_scope,
        "tech_ignored": tech_ignored,
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
        designated_values = [
            r["decision_adherence_in_designated_section"] for r in version_runs
            if isinstance(r["decision_adherence_in_designated_section"], (int, float))
        ]
        aggregate[version]["decision_adherence_in_designated_section"] = (
            _mean(designated_values) if designated_values else "n/a"
        )

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
                      "tech_counts | tech_ignored | jev_requests |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
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
                tech_ignored = "; ".join(
                    ",".join(f"{term}={c}" for term, c in ignored.items() if c > 0) or "-"
                    for ignored in r["tech_ignored"].values()
                )
                lines.append(
                    f"| {r['version']} | {r['repeat']} | {r['sections_found']} | {r['fallback_lines']} | "
                    f"{r['design_warnings']} | {r['placeholder_hits']} | {r['jargon_hits']} | "
                    f"{r['leak_hits']} | {r['retries']} | {_fmt(r['decision_adherence'])} | "
                    f"{r['numeric_claims']} | {r['unsupported_numbers']} | {r['assumption_mentions']} | "
                    f"{tech} | {tech_counts} | {tech_ignored} | {r['jev_requests']} |"
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
    lines.append(
        f"| decision_adherence_in_designated_section | n/a | "
        f"{_fmt(data['aggregate']['B'].get('decision_adherence_in_designated_section', 'n/a'))} |"
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
