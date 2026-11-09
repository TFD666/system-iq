"""
Regenerate ONLY the design sections a validation pass flagged. Reuses
the design writer's prompt rules and per-group quality gate (writer.py)
so a revised section reads the same as an original one -- this module
just points the same machinery at a smaller "pseudo-group" of sections.

Never touches section 13 (the code-generated assumptions section) -- the
caller is expected to only pass section numbers 1-12 here.
"""

from __future__ import annotations

import difflib
import logging
import re

from ..design.checks import split_into_sections
from ..design.limiter import TokenBudget
from ..design.sections import all_headings, heading_number, section_heading_by_number
from ..design.writer import (
    _build_retry_user_message,
    _build_system_prompt,
    _build_user_message,
    _decisions_summary,
    _label_for,
    _max_tokens_per_group,
    _replace_leftover_identifiers,
    _requirements_summary,
    _validate_group,
)
from ..llm import LLMProvider
from ..schemas import DecisionResultOut, Requirements
from .policy import ValidationResult

logger = logging.getLogger(__name__)

# Regenerate at most this many sections in one LLM call.
MAX_SECTIONS_PER_REVISE_CALL = 3

# Plain, fixed issue statements per validation question id -- never the
# raw Jev probability number, and never prompt/model text in logs.
_ISSUE_TEMPLATES = {
    "val_geospatial": (
        "The design must clearly state how location-based queries are "
        "supported, for example with a spatial index or a geospatial database."
    ),
    "val_search": "The design must clearly state how users search or filter results.",
    "val_auth": "The design must clearly state how user authentication works.",
    "val_missing_component": (
        "The validation found that a component these requirements need is "
        "missing from the design. Identify the most likely missing component, "
        "for example where the application's data comes from, a storage "
        "component or an external service the requirements imply. Add it to "
        "the sections you are rewriting, name it, say what it does and how "
        "it connects to the other components. If the requirements do not "
        "name it, label it as an assumption in one sentence."
    ),
    "val_invented": "Remove any feature that is not in the requirements.",
    "val_contradiction": "Make sure no two sections contradict each other; resolve any contradiction.",
    "val_unneeded_complexity": "Simplify the design; it must not be more complex than these requirements need.",
    "val_scale_overclaim": (
        "Remove any claim about a specific load or scale that the "
        "requirements do not state."
    ),
}

# Post-revision sanity check thresholds (see _revision_is_acceptable).
_MIN_WORD_CHANGE_RATIO = 0.25
_BOLD_RE = re.compile(r"\*\*([^*]{2,80})\*\*")
_CAPITALIZED_PHRASE_RE = re.compile(r"\b(?:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b")


def _issue_statement(result: ValidationResult, decisions: list[DecisionResultOut] | None) -> str:
    if result.id.startswith("val_decision_"):
        decision_id = result.id[len("val_decision_"):]
        decision = next((d for d in (decisions or []) if d.id == decision_id), None)
        if decision is not None:
            return f"The design must clearly state that it uses {decision.choice} for {_label_for(decision_id)}."
    return _ISSUE_TEMPLATES.get(result.id, "Fix the issue this section was flagged for.")


def _word_change_ratio(old_text: str, new_text: str) -> float:
    """Fraction of words changed between old and new, word-level and
    case-insensitive (1 - SequenceMatcher's match ratio)."""
    old_words = old_text.lower().split()
    new_words = new_text.lower().split()
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    return 1 - matcher.ratio()


def _component_like_phrases(text: str) -> set[str]:
    """Crude heuristic for named components: bolded names, or two-or-more
    consecutive Capitalized Words (e.g. "Storage Service")."""
    return {p.strip().lower() for p in _BOLD_RE.findall(text)} | {
        p.lower() for p in _CAPITALIZED_PHRASE_RE.findall(text)
    }


def _introduces_new_component(old_text: str, new_text: str) -> bool:
    return bool(_component_like_phrases(new_text) - _component_like_phrases(old_text))


def _revision_is_acceptable(old_text: str, new_text: str, needs_new_component: bool) -> bool:
    if _word_change_ratio(old_text, new_text) < _MIN_WORD_CHANGE_RATIO:
        return False
    if needs_new_component and not _introduces_new_component(old_text, new_text):
        return False
    return True


def _sections_to_revise(flagged_results: list[ValidationResult]) -> list[int]:
    """Union of section numbers from flagged results, sorted. 1-12 only -- never 13."""
    numbers = {n for result in flagged_results for n in result.sections if 1 <= n <= 12}
    return sorted(numbers)


def _chunk(items: list[int], size: int) -> list[list[int]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def revise_sections(
    markdown: str,
    flagged_results: list[ValidationResult],
    requirements: Requirements,
    decisions: list[DecisionResultOut] | None,
    llm: LLMProvider,
    budget: TokenBudget,
) -> tuple[str, list[int], list[str]]:
    """
    Regenerate only the sections flagged_results point to.
    Returns (new_markdown, revised_section_numbers, warnings). A section
    that still fails the quality gate after one retry keeps its OLD text
    (never the fallback line) and adds a warning instead.
    """
    section_numbers = _sections_to_revise(flagged_results)
    if not section_numbers:
        return markdown, [], []

    headings = all_headings()
    heading_by_number = {n: s["heading"] for n, s in section_heading_by_number().items()}
    bodies = split_into_sections(markdown, headings)

    issue_lines = [_issue_statement(r, decisions) for r in flagged_results]
    decisions_summary = _decisions_summary(decisions)
    requirements_summary = _requirements_summary(requirements)
    max_tokens = _max_tokens_per_group()

    revised: set[int] = set()
    warnings: list[str] = []

    for chunk_numbers in _chunk(section_numbers, MAX_SECTIONS_PER_REVISE_CALL):
        chunk_headings = [heading_by_number[n] for n in chunk_numbers]
        pseudo_group = {
            "id": "revise_" + "_".join(str(n) for n in chunk_numbers),
            "sections": [
                {"heading": h, "guidance": section_heading_by_number()[n]["guidance"]}
                for n, h in zip(chunk_numbers, chunk_headings)
            ],
        }

        current_text = "\n\n".join(f"{h}\n{bodies.get(h) or ''}" for h in chunk_headings)
        user_message = (
            _build_user_message(requirements_summary, decisions_summary)
            + "\n\nCurrent text of the sections to revise:\n" + current_text
            + "\n\nFix these issues:\n" + "\n".join(f"- {line}" for line in issue_lines)
            + "\nWrite ALL of these headings again, in full, in this exact order:\n"
            + "\n".join(chunk_headings)
        )
        system_prompt = _build_system_prompt(pseudo_group, requirements.app_type, decisions)

        def _call(message: str) -> str:
            estimated_total = (len(system_prompt) + len(message)) // 4 + max_tokens
            budget.wait_if_needed(estimated_total, max_tokens)
            result = llm.complete_text(system=system_prompt, user=message, max_tokens=max_tokens)
            budget.record(result.prompt_tokens + result.completion_tokens, result.completion_tokens)
            return result.text

        # Numbers/ids only in the log -- never prompt text or model output.
        logger.info("validation: revising section(s) %s", chunk_numbers)
        text = _call(user_message)
        bad = _validate_group(pseudo_group, text)

        if bad:
            retry_message = _build_retry_user_message(user_message, pseudo_group, bad)
            text = _call(retry_message)
            bad = _validate_group(pseudo_group, text)

        text = _replace_leftover_identifiers(text)
        new_bodies = split_into_sections(text, chunk_headings)

        for heading in chunk_headings:
            if heading in bad:
                # Quality gate still failing after the retry: keep the
                # OLD text untouched, never junk or a generic fallback line.
                warnings.append(f"revision quality gate failed: {heading}")
                continue

            old_text = bodies.get(heading) or ""
            new_text = new_bodies.get(heading) or old_text
            hn = heading_number(heading)
            ids_for_heading = [r.id for r in flagged_results if hn in r.sections]
            needs_new_component = "val_missing_component" in ids_for_heading
            if not _revision_is_acceptable(old_text, new_text, needs_new_component):
                warn_id = ids_for_heading[0] if ids_for_heading else pseudo_group["id"]
                warnings.append(f"revision no change: {warn_id}")
                continue

            bodies[heading] = new_text
            revised.add(hn)

    new_markdown = "\n\n".join(f"{h}\n{bodies[h]}" for h in headings)
    return new_markdown, sorted(revised), warnings
