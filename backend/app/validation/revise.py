"""
Regenerate ONLY the design sections a validation pass flagged. Reuses
the design writer's prompt rules and per-group quality gate (writer.py)
so a revised section reads the same as an original one -- this module
just points the same machinery at a smaller "pseudo-group" of sections.

Never touches section 13 (the code-generated assumptions section) -- the
caller is expected to only pass section numbers 1-12 here.
"""

from __future__ import annotations

import logging

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
        "The design must explain how location-based queries are supported, "
        "for example with a spatial index or a geospatial database."
    ),
    "val_search": "The design must describe how users search or filter results.",
    "val_auth": "The design must address user authentication.",
    "val_missing_component": "Add any component these requirements need that is missing from the design.",
    "val_invented": (
        "Remove claims that are not in the requirements, for example "
        "features like reviews, ratings, or user accounts that were not requested."
    ),
    "val_contradiction": "Make sure no two sections contradict each other; resolve any contradiction.",
    "val_unneeded_complexity": "Simplify the design; it must not be more complex than these requirements need.",
    "val_scale_overclaim": (
        "Remove any claim about handling a specific load or scale that the "
        "requirements do not state."
    ),
}


def _issue_statement(result: ValidationResult, decisions: list[DecisionResultOut] | None) -> str:
    if result.id.startswith("val_decision_"):
        decision_id = result.id[len("val_decision_"):]
        decision = next((d for d in (decisions or []) if d.id == decision_id), None)
        if decision is not None:
            return f"The design must clearly use {decision.choice} for {_label_for(decision_id)}."
    return _ISSUE_TEMPLATES.get(result.id, "Fix the issue this section was flagged for.")


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
    decisions_present = bool(decisions)
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
        system_prompt = _build_system_prompt(pseudo_group, requirements.app_type)

        def _call(message: str) -> str:
            estimated_total = (len(system_prompt) + len(message)) // 4 + max_tokens
            budget.wait_if_needed(estimated_total, max_tokens)
            result = llm.complete_text(system=system_prompt, user=message, max_tokens=max_tokens)
            budget.record(result.prompt_tokens + result.completion_tokens, result.completion_tokens)
            return result.text

        # Numbers/ids only in the log -- never prompt text or model output.
        logger.info("validation: revising section(s) %s", chunk_numbers)
        text = _call(user_message)
        bad = _validate_group(pseudo_group, text, decisions_present)

        if bad:
            retry_message = _build_retry_user_message(user_message, pseudo_group, bad)
            text = _call(retry_message)
            bad = _validate_group(pseudo_group, text, decisions_present)

        text = _replace_leftover_identifiers(text)
        new_bodies = split_into_sections(text, chunk_headings)

        for heading in chunk_headings:
            if heading in bad:
                # Quality gate still failing after the retry: keep the
                # OLD text untouched, never junk or a generic fallback line.
                warnings.append(f"revision quality gate failed: {heading}")
                continue
            bodies[heading] = new_bodies.get(heading) or bodies.get(heading) or ""
            revised.add(heading_number(heading))

    new_markdown = "\n\n".join(f"{h}\n{bodies[h]}" for h in headings)
    return new_markdown, sorted(revised), warnings
