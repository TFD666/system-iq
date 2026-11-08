"""
Generate the seeded design variants: reads base_design.md, applies one
small, deliberate defect to each variant (a single section edit), and
writes eval/seeded/variants/<id>.md plus eval/seeded/ground_truth.json.

Standard library only. Every mutation is checked two ways:
  1. the target section actually changed (else: a clear error)
  2. every OTHER section is byte-identical to the base (else: a clear error)
so a bug in a mutation can never silently corrupt an unrelated section.

Output here is ASCII-only (no fancy punctuation) and never prints the
design text itself -- only variant ids, section numbers, and counts.
"""

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
BASE_PATH = HERE / "base_design.md"
VARIANTS_DIR = HERE / "variants"
GROUND_TRUTH_PATH = HERE / "ground_truth.json"

# "## <n>." at the start of a line marks a section heading.
_HEADING_RE = re.compile(r"^## (\d+)\..*$", re.MULTILINE)


def section_bounds(text: str) -> dict[int, tuple[int, int]]:
    """Map section number -> (start, end) character offsets in `text`."""
    matches = list(_HEADING_RE.finditer(text))
    bounds: dict[int, tuple[int, int]] = {}
    for i, match in enumerate(matches):
        number = int(match.group(1))
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bounds[number] = (start, end)
    return bounds


def section_texts(text: str) -> dict[int, str]:
    return {n: text[start:end] for n, (start, end) in section_bounds(text).items()}


def apply_section_mutation(text: str, section_number: int, transform, variant_id: str) -> str:
    """
    Replace section `section_number`'s text with transform(old_text).
    Raises ValueError (naming the variant) if the transform didn't change
    anything, or if any OTHER section ended up different from the base.
    """
    before = section_texts(text)
    if section_number not in before:
        raise ValueError(f"{variant_id}: section {section_number} not found")

    old_section = before[section_number]
    new_section = transform(old_section)
    if new_section == old_section:
        raise ValueError(f"{variant_id}: mutation did not change section {section_number}")

    start, end = section_bounds(text)[section_number]
    new_text = text[:start] + new_section + text[end:]

    after = section_texts(new_text)
    for number, old_body in before.items():
        if number == section_number:
            continue
        if after.get(number) != old_body:
            raise ValueError(f"{variant_id}: section {number} changed unexpectedly")

    return new_text


# ── small, reusable edits ───────────────────────────────────────────────────

_V01_PHRASES = ("venue data source", "venue directory", "imported dataset")


def _contains_v01_phrase(fragment: str) -> bool:
    lowered = fragment.lower()
    return any(phrase in lowered for phrase in _V01_PHRASES)


def remove_v01_phrases(section_text: str) -> str:
    """
    Drop every bullet line, or every sentence within a plain paragraph
    line, that mentions a venue-data-source phrase. Nothing else changes
    (the map provider lines, in particular, must survive).
    """
    out_lines = []
    for line in section_text.split("\n"):
        if line.strip().startswith("- "):
            if _contains_v01_phrase(line):
                continue  # drop the whole bullet
            out_lines.append(line)
            continue

        # Plain paragraph line: split into sentences, drop the matching ones.
        sentences = re.split(r"(?<=\.)\s+", line)
        kept = [s for s in sentences if not _contains_v01_phrase(s)]
        if kept == sentences:
            out_lines.append(line)  # nothing in this line matched
        else:
            out_lines.append(" ".join(kept).strip())
    return "\n".join(out_lines)


def append_to_section(section_text: str, addition: str) -> str:
    return section_text.rstrip() + "\n\n" + addition + "\n\n"


def replace_body_keep_heading(section_text: str, new_body: str) -> str:
    heading_line = section_text.split("\n", 1)[0]
    return heading_line + "\n\n" + new_body + "\n\n"


# ── the 9 variants ───────────────────────────────────────────────────────────

V02_LINE = (
    "- **Engagement features**: The system also sends push notifications "
    "and supports user reviews and ratings."
)
V05_PARAGRAPH = "The system is built to handle 10 million users and 50,000 requests per second."
V06_SENTENCE = (
    "The system is split into twelve microservices running on Kubernetes "
    "with Kafka for messaging."
)
V07_PARAGRAPH = "Horizontal scaling across many servers is required."
V08_BODY = (
    "The purple authentication of regulated sandwiches faces lower verification. "
    "Tokens certify the weather of users. The scope is questionable by cabbage."
)


def _mutate_v01(base: str, variant_id: str) -> str:
    text = apply_section_mutation(base, 2, remove_v01_phrases, variant_id)
    text = apply_section_mutation(text, 8, remove_v01_phrases, variant_id)
    return text


def _mutate_v02(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 2, lambda s: append_to_section(s, V02_LINE), variant_id)


def _mutate_v03(base: str, variant_id: str) -> str:
    return apply_section_mutation(
        base, 4,
        lambda s: re.sub(r"\bREST(ful)?\b", "GraphQL", s, flags=re.IGNORECASE),
        variant_id,
    )


def _mutate_v04(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 5, lambda s: s.replace("PostGIS", "MongoDB"), variant_id)


def _mutate_v05(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 10, lambda s: append_to_section(s, V05_PARAGRAPH), variant_id)


def _mutate_v06(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 1, lambda s: append_to_section(s, V06_SENTENCE), variant_id)


def _mutate_v07(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 10, lambda s: append_to_section(s, V07_PARAGRAPH), variant_id)


def _mutate_v08(base: str, variant_id: str) -> str:
    return apply_section_mutation(base, 6, lambda s: replace_body_keep_heading(s, V08_BODY), variant_id)


VARIANTS = [
    {
        "id": "v00_base",
        "mutate": lambda base, vid: base,
        "expected_flagged": [],
        "description": "Unchanged base design; nothing should be flagged.",
    },
    {
        "id": "v01_missing_component",
        "mutate": _mutate_v01,
        "expected_flagged": ["val_missing_component"],
        "description": "Removes the venue-data-source component; the map provider stays.",
    },
    {
        "id": "v02_invented_feature",
        "mutate": _mutate_v02,
        "expected_flagged": ["val_invented"],
        "description": "Adds push notifications, reviews, and ratings -- none were requested.",
    },
    {
        "id": "v03_decision_violated_api",
        "mutate": _mutate_v03,
        "expected_flagged": ["val_decision_api_style"],
        "description": "Switches the API style to GraphQL, contradicting the accepted REST decision.",
    },
    {
        "id": "v04_decision_violated_db",
        "mutate": _mutate_v04,
        "expected_flagged": ["val_decision_primary_database"],
        "description": "Swaps PostGIS for MongoDB, contradicting the accepted database decision.",
    },
    {
        "id": "v05_scale_overclaim",
        "mutate": _mutate_v05,
        "expected_flagged": ["val_scale_overclaim"],
        "description": "Claims specific user/traffic numbers the requirements never stated.",
    },
    {
        "id": "v06_complexity",
        "mutate": _mutate_v06,
        "expected_flagged": ["val_unneeded_complexity", "val_decision_architecture_style"],
        "description": "Adds a 12-microservice/Kubernetes/Kafka architecture, contradicting the "
                        "decided monolith and overcomplicating the design.",
    },
    {
        "id": "v07_contradiction",
        "mutate": _mutate_v07,
        "expected_flagged": ["val_contradiction"],
        "description": "Claims horizontal scaling is required, contradicting section 10's "
                        "earlier statement that it is not.",
    },
    {
        "id": "v08_incoherent",
        "mutate": _mutate_v08,
        "expected_flagged": ["val_incoherent"],
        "description": "Replaces the authentication section with nonsensical text.",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate seeded design variants.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing variant files.")
    args = parser.parse_args()

    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    base = BASE_PATH.read_text(encoding="utf-8")

    ground_truth = {}
    written = 0
    skipped = 0

    for variant in VARIANTS:
        variant_id = variant["id"]
        out_path = VARIANTS_DIR / f"{variant_id}.md"

        if out_path.exists() and not args.force:
            print(f"refused to overwrite existing variant: {variant_id} (use --force)")
            skipped += 1
        else:
            text = variant["mutate"](base, variant_id)
            out_path.write_text(text, encoding="utf-8")
            print(f"wrote variant: {variant_id}")
            written += 1

        ground_truth[variant_id] = {
            "expected_flagged": variant["expected_flagged"],
            "description": variant["description"],
        }

    GROUND_TRUTH_PATH.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    print(f"wrote: {GROUND_TRUTH_PATH.name}")
    print(f"variants written: {written}, skipped (already existed): {skipped}")


if __name__ == "__main__":
    main()
