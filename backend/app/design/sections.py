"""
The list of Markdown sections the design document is made of.

Sections are split into 4 groups so each LLM call only has to write a
few headings at a time (keeps prompts small and keeps unrelated topics,
like security and scaling, from bleeding into each other).

Section 13 ("Assumptions and open questions") is NOT in here: it is built
by code in writer.py, not written by the LLM.
"""

import os

ASSUMPTIONS_HEADING = "## 13. Assumptions and open questions"

# Word target per LLM-written section. The minimum is lower than the max
# target because padding a short, correct answer with filler to hit a high
# minimum is exactly the "junk output" bug this was built to avoid.
DEFAULT_MIN_WORDS_PER_SECTION = 40
MAX_WORDS_PER_SECTION = 140


def min_words_per_section() -> int:
    # Read lazily (not at import time) so tests can set DESIGN_MIN_WORDS first.
    return int(os.environ.get("DESIGN_MIN_WORDS", DEFAULT_MIN_WORDS_PER_SECTION))

SECTION_GROUPS = [
    {
        "id": "g1",
        "sections": [
            {
                "heading": "## 1. Architecture overview",
                "guidance": (
                    "Summarize the overall architecture style (monolith, modular\n"
                    "monolith, or microservices) and why it fits this project.\n"
                    "Name the main building blocks at a high level."
                ),
            },
            {
                "heading": "## 2. Components and responsibilities",
                "guidance": (
                    "List the main components or services and what each one owns.\n"
                    "Keep each component to one or two sentences.\n"
                    "Use a bullet list."
                ),
            },
            {
                "heading": "## 3. Data flow",
                "guidance": (
                    "Describe how a typical request moves through the system,\n"
                    "end to end. Mention where data is read from and written to.\n"
                    "Keep it short."
                ),
            },
        ],
    },
    {
        "id": "g2",
        "sections": [
            {
                "heading": "## 4. API architecture",
                "guidance": (
                    "State the API style (REST, GraphQL, or gRPC) and why it fits.\n"
                    "Describe the main endpoints or operations at a high level.\n"
                    "Mention versioning or error handling only if relevant."
                ),
            },
            {
                "heading": "## 5. Database architecture and data model",
                "guidance": (
                    "Name the chosen database and the main entities it stores.\n"
                    "Describe relationships between entities briefly.\n"
                    "Mention indexing or partitioning only if scale requires it."
                ),
            },
        ],
    },
    {
        "id": "g3",
        "sections": [
            {
                "heading": "## 6. Authentication",
                "guidance": (
                    "Describe the authentication approach and who it applies to.\n"
                    "Mention session or token lifetime only if relevant.\n"
                    "Keep it to a short paragraph."
                ),
            },
            {
                "heading": "## 7. Caching",
                "guidance": (
                    "State whether caching is needed and what it would cache.\n"
                    "Name the caching layer if one was chosen.\n"
                    "Say 'not needed' if caching was decided against."
                ),
            },
            {
                "heading": "## 8. External services",
                "guidance": (
                    "List external services or integrations this project depends on.\n"
                    "Describe what each one is used for in one sentence.\n"
                    "Use generic names, not real vendor names."
                ),
            },
            {
                "heading": "## 9. Security considerations",
                "guidance": (
                    "List the main security risks and how the design addresses them.\n"
                    "Mention input validation, secrets handling, and access control.\n"
                    "Keep it to a short bullet list."
                ),
            },
        ],
    },
    {
        "id": "g4",
        "sections": [
            {
                "heading": "## 10. Scaling",
                "guidance": (
                    "Describe how the system would handle growth in users or traffic.\n"
                    "Mention horizontal scaling only if the decisions call for it.\n"
                    "Keep it short."
                ),
            },
            {
                "heading": "## 11. Failure handling",
                "guidance": (
                    "Describe what happens when a dependency or component fails.\n"
                    "Mention retries, timeouts, or fallbacks only if relevant.\n"
                    "Keep it to a short paragraph."
                ),
            },
            {
                "heading": "## 12. Trade-offs and rationale",
                "guidance": (
                    "Summarize the main trade-offs made in this design.\n"
                    "Explain briefly why alternatives were not chosen.\n"
                    "Keep it to a short bullet list."
                ),
            },
        ],
    },
]


def all_headings() -> list[str]:
    """Every heading the finished document should have, in order."""
    headings = []
    for group in SECTION_GROUPS:
        for section in group["sections"]:
            headings.append(section["heading"])
    headings.append(ASSUMPTIONS_HEADING)  # code-generated, not from the LLM
    return headings


def heading_number(heading: str) -> int:
    """"## 13. Assumptions and open questions" -> 13. Used by validation/
    revise.py to map a section number back to its heading text."""
    return int(heading.split()[1].rstrip("."))


def section_heading_by_number() -> dict[int, dict]:
    """Map section number (1-12 only -- never 13) to its {"heading",
    "guidance"} dict, for revise.py to rebuild a pseudo-group to reuse
    the writer's per-group prompt/quality-gate machinery."""
    mapping: dict[int, dict] = {}
    for group in SECTION_GROUPS:
        for section in group["sections"]:
            mapping[heading_number(section["heading"])] = section
    return mapping
