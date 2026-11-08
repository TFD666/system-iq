"""
Deterministic checks run on the generated design Markdown.

These never read or echo back generated prose into their warnings: every
warning is built only from ids, headings, and category words, so it's
always safe to log or display. The actual text is only ever matched
against, never copied out.
"""

import re

from .sections import ASSUMPTIONS_HEADING, MAX_WORDS_PER_SECTION, all_headings

# Matches the language tag on an OPENING fenced code block, e.g. "```python".
# (A closing "```" has no language tag, which is allowed, so it never matches.)
_FENCE_LANG_RE = re.compile(r"^```(\S*)", re.MULTILINE)

_ALLOWED_FENCE_LANGUAGES = {"", "text", "mermaid"}

# Placeholder phrases the model sometimes writes instead of real content.
PLACEHOLDER_PHRASES = ("tbd", "to be determined", "not finalized")

# Internal identifiers that must never leak into the prose -- the prompt
# tells the model to describe these in plain words instead.
JARGON_TOKENS = ("needs_review", "based_on_unknowns", "decision status")

# A vague, invented deadline like "within 30 days" / "within 2 weeks".
WITHIN_N_DEADLINE_RE = re.compile(
    r"within\s+\d+\s+(day|days|week|weeks|month|months)", re.IGNORECASE
)

# Said only when decisions WERE provided but the model still claims it
# picked the technology itself.
MODEL_CHOSEN_PHRASES = ("model chosen", "chosen by the model")


def split_into_sections(markdown: str, headings: list[str]) -> dict[str, str | None]:
    """
    Map each heading to the text between it and the next heading (or the
    end of the document). A heading maps to None if it isn't present at
    all. Shared by writer.py (per-group validation) and check_design
    (whole-document checks) so both agree on where a section "ends".
    """
    found = sorted(
        (idx, heading) for heading in headings if (idx := markdown.find(heading)) != -1
    )
    bodies: dict[str, str | None] = {heading: None for heading in headings}
    for position, (start_idx, heading) in enumerate(found):
        body_start = start_idx + len(heading)
        body_end = found[position + 1][0] if position + 1 < len(found) else len(markdown)
        bodies[heading] = markdown[body_start:body_end].strip()
    return bodies


def check_design(markdown: str, decisions) -> list[str]:
    """Return a list of short warning strings; empty if nothing is wrong."""
    warnings: list[str] = []
    warnings.extend(_check_missing_headings(markdown))
    warnings.extend(_check_accepted_choices_are_mentioned(markdown, decisions))
    warnings.extend(_check_fenced_code_languages(markdown))
    warnings.extend(_check_leftover_jargon_or_placeholders(markdown))
    warnings.extend(_check_section_lengths(markdown))
    warnings.extend(_check_repeated_lines(markdown))
    return warnings


def _check_missing_headings(markdown: str) -> list[str]:
    # A heading that isn't written with the exact "## N. ..." text (e.g.
    # missing the "## " prefix) also fails this substring check, so a
    # malformed heading is correctly reported as missing too.
    return [
        f"missing heading: {heading}"
        for heading in all_headings()
        if heading not in markdown
    ]


def _check_accepted_choices_are_mentioned(markdown: str, decisions) -> list[str]:
    # An "accepted" choice decision is a fixed fact; the document should
    # actually name it, case-insensitively, somewhere in the text.
    markdown_lower = markdown.lower()
    warnings: list[str] = []
    for decision in decisions or []:
        if decision.status == "accepted" and decision.choice:
            if decision.choice.lower() not in markdown_lower:
                warnings.append(f"missing accepted choice for {decision.id}")
    return warnings


def _check_fenced_code_languages(markdown: str) -> list[str]:
    # The LLM was told not to write application code or config files, so a
    # fenced block of e.g. "python" or "yaml" means it broke that rule.
    warnings: list[str] = []
    for match in _FENCE_LANG_RE.finditer(markdown):
        language = match.group(1).strip().lower()
        if language not in _ALLOWED_FENCE_LANGUAGES:
            warnings.append(f"disallowed code fence language: {language}")
    return warnings


def _check_leftover_jargon_or_placeholders(markdown: str) -> list[str]:
    lowered = markdown.lower()
    warnings: list[str] = []
    for phrase in PLACEHOLDER_PHRASES:
        if phrase in lowered:
            warnings.append(f"placeholder text: {phrase}")
    for token in JARGON_TOKENS:
        if token in lowered:
            warnings.append(f"leftover jargon: {token}")
    if WITHIN_N_DEADLINE_RE.search(markdown):
        warnings.append("invented deadline phrase")
    return warnings


def _check_section_lengths(markdown: str) -> list[str]:
    # Flags a section whose body ran far past the word target -- the
    # per-group retry in writer.py already catches TOO SHORT sections, so
    # this is only about the opposite problem (rambling).
    headings = all_headings()
    bodies = split_into_sections(markdown, headings)
    too_long_limit = MAX_WORDS_PER_SECTION * 2
    warnings: list[str] = []
    for heading in headings:
        body = bodies.get(heading)
        if body and len(body.split()) > too_long_limit:
            warnings.append(f"section far over word target: {heading}")
    return warnings


def _check_repeated_lines(markdown: str) -> list[str]:
    # Catches a bullet or sentence that exactly restates an earlier one in
    # the same section (padding-by-repetition instead of real content).
    # Section 13 is code-built (never LLM prose), so it's never checked --
    # and its "- None." placeholder lines are not repetition either way.
    # Split against ALL headings (so section 13 still marks where section
    # 12's body ends), then simply skip it when generating warnings.
    all_heads = all_headings()
    bodies = split_into_sections(markdown, all_heads)
    warnings: list[str] = []
    for heading in all_heads:
        if heading == ASSUMPTIONS_HEADING:
            continue
        body = bodies.get(heading)
        if not body:
            continue
        seen: set[str] = set()
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                continue  # fence delimiters legitimately repeat; not real content
            key = stripped.lstrip("-*•").strip().lower()
            if not key or key == "none":
                continue
            if key in seen:
                warnings.append(f"repetition: {heading}")
                break
            seen.add(key)
    return warnings
