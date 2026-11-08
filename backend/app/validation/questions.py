"""
Build the Jev noul questions used to validate a FINISHED design against
its own requirements and decisions. These are ordinary Jev questions
(Question/Decision from the decision package); "validation" just means
we ask them about the design document instead of about the requirements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..decision.provider import Question
from ..design.checks import split_into_sections
from ..design.sections import all_headings, heading_number
from ..design.writer import _label_for, _requirements_summary
from ..schemas import DecisionResultOut, Requirements

# A validation question's id maps to the design section number(s) its
# answer is about, so a "flagged" result tells revise.py what to rewrite.
DECISION_SECTION_MAP = {
    "api_style": [4],
    "primary_database": [5],
    "architecture_style": [1, 2],
    "auth_approach": [6],
    "realtime_transport": [3],
    "media_storage_approach": [5],
}

# build_validation_state refuses anything bigger than this (characters).
MAX_STATE_CHARS = 20_000


class ValidationStateTooLargeError(Exception):
    """The serialized validation state was over MAX_STATE_CHARS."""


@dataclass
class ValidationQuestion:
    id: str
    text: str
    polarity: str  # "satisfied" | "problem"
    sections: list[int]  # which design sections this answer is about


def build_validation_questions(
    requirements: Requirements, decisions: list[DecisionResultOut] | None
) -> list[ValidationQuestion]:
    """
    Build the fixed-template validation questions for this run. Which
    "satisfied" questions appear depends on the requirements and
    decisions; the five "problem" questions are always asked.
    """
    questions: list[ValidationQuestion] = []

    if requirements.geospatial is True:
        questions.append(ValidationQuestion(
            id="val_geospatial",
            polarity="satisfied",
            sections=[4, 5],
            text=(
                "Does the design explain how nearby, location-based queries "
                "are supported, for example with a spatial index or a "
                "geospatial database?"
            ),
        ))

    if requirements.search_filtering is True:
        questions.append(ValidationQuestion(
            id="val_search",
            polarity="satisfied",
            sections=[4],
            text="Does the design describe how users search or filter results?",
        ))

    if requirements.authentication is True:
        questions.append(ValidationQuestion(
            id="val_auth",
            polarity="satisfied",
            sections=[6],
            text="Does the design address user authentication?",
        ))

    for decision in decisions or []:
        if decision.status == "accepted" and decision.id in DECISION_SECTION_MAP:
            questions.append(ValidationQuestion(
                id=f"val_decision_{decision.id}",
                polarity="satisfied",
                sections=DECISION_SECTION_MAP[decision.id],
                text=f"Does the design clearly use {decision.choice} for {_label_for(decision.id)}?",
            ))

    questions.append(ValidationQuestion(
        id="val_missing_component",
        polarity="problem",
        sections=[2, 8],
        text=(
            "Is any component that these requirements need missing from "
            "the design, for example a source of the venue data?"
        ),
    ))
    questions.append(ValidationQuestion(
        id="val_invented",
        polarity="problem",
        sections=[2, 5],
        text=(
            "Does the design present features or requirements that are not "
            "in the requirements, for example reviews, ratings or user accounts?"
        ),
    ))
    questions.append(ValidationQuestion(
        id="val_contradiction",
        polarity="problem",
        sections=[],
        text="Do any two sections of the design contradict each other?",
    ))
    questions.append(ValidationQuestion(
        id="val_unneeded_complexity",
        polarity="problem",
        sections=[],
        text="Is the design more complex than these requirements need?",
    ))
    questions.append(ValidationQuestion(
        id="val_scale_overclaim",
        polarity="problem",
        sections=[10],
        text=(
            "Does the design claim it can handle a specific load or scale "
            "that the requirements do not state?"
        ),
    ))
    questions.append(ValidationQuestion(
        id="val_incoherent",
        polarity="problem",
        sections=[],
        text="Does any section of the design contain unclear, nonsensical or meaningless text?",
    ))

    return questions


def to_jev_questions(questions: list[ValidationQuestion]) -> list[Question]:
    """Every validation question is a plain Jev noul question."""
    return [Question(id=q.id, kind="noul", text=q.text) for q in questions]


def build_validation_state(
    requirements: Requirements,
    decisions: list[DecisionResultOut] | None,
    design_markdown: str,
) -> dict:
    """
    A compact dict for the Jev "state" field: requirements (reusing the
    writer's own summary, which already drops project_summary and raw
    idea text), decisions (label/status/choice only), and the design
    broken into numbered sections (section 13 included). Refuses
    (raises ValidationStateTooLargeError) if this is over 20000 chars.
    """
    decisions_summary = [
        {"label": _label_for(d.id), "status": d.status, "choice": d.choice}
        for d in (decisions or [])
    ]

    headings = all_headings()
    bodies = split_into_sections(design_markdown, headings)
    design_sections = [
        {"number": heading_number(heading), "heading": heading, "text": bodies.get(heading) or ""}
        for heading in headings
    ]

    state = {
        "requirements": _requirements_summary(requirements),
        "decisions": decisions_summary,
        "design": design_sections,
    }

    serialized_length = len(json.dumps(state, separators=(",", ":")))
    if serialized_length > MAX_STATE_CHARS:
        raise ValidationStateTooLargeError(
            f"validation state is {serialized_length} characters, over the {MAX_STATE_CHARS} limit"
        )

    return state
