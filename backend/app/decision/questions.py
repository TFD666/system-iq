"""
Build the state dict and Question list from a Requirements object.
The state dict is sent to Jev as the "context" for every question.
"""

from __future__ import annotations

from typing import Any

from ..schemas import Requirements
from .provider import Question


def build_state(req: Requirements) -> dict[str, Any]:
    """
    Return the requirements as a plain dict for the Jev state field.
    Raw idea text is never included – only structured fields.
    """
    return {
        "project_summary": req.project_summary,
        "app_type": req.app_type,
        "core_features": req.core_features,
        "user_roles": req.user_roles,
        "expected_scale": {
            "users": req.expected_scale.users,
            "peak_requests_per_second": req.expected_scale.peak_requests_per_second,
            "data_volume": req.expected_scale.data_volume,
        },
        "realtime": req.realtime,
        "geospatial": req.geospatial,
        "authentication": req.authentication,
        "search_filtering": req.search_filtering,
        "media_storage": req.media_storage,
        "payments": req.payments,
        "offline_support": req.offline_support,
        "external_integrations": req.external_integrations,
        "constraints": req.constraints,
        "assumptions": req.assumptions,
        "unknowns": req.unknowns,
    }


def build_questions(req: Requirements) -> list[Question]:
    """
    Build the list of Jev questions tailored to this requirements object.
    Conditional questions are only included when the relevant flag is set.
    """
    questions: list[Question] = []

    # Always: which API style fits best?
    questions.append(Question(
        id="api_style",
        kind="choice",
        text="Which API communication style best fits this project's needs?",
        options=["REST", "GraphQL", "gRPC"],
        depends_on=["core_features", "app_type"],
    ))

    # Always: primary database – PostGIS option added only for geospatial apps.
    db_options = ["PostgreSQL", "MongoDB", "DynamoDB"]
    if req.geospatial is True:
        db_options.append("PostgreSQL + PostGIS")
    questions.append(Question(
        id="primary_database",
        kind="choice",
        text="Which database best suits the data storage needs of this project?",
        options=db_options,
        depends_on=["geospatial", "expected_scale"],
    ))

    # Always: how should the system be structured?
    questions.append(Question(
        id="architecture_style",
        kind="choice",
        text="Which architecture style is most appropriate for this project's scale?",
        options=["monolith", "modular monolith", "microservices"],
        depends_on=["expected_scale"],
    ))

    # Always: noul questions about infrastructure needs.
    questions.append(Question(
        id="cache_needed",
        kind="noul",
        text="Does this project need a caching layer to meet its performance requirements?",
        depends_on=["expected_scale"],
    ))

    questions.append(Question(
        id="async_processing_needed",
        kind="noul",
        text="Does this project need asynchronous or background job processing?",
        depends_on=["core_features", "realtime"],
    ))

    questions.append(Question(
        id="horizontal_scaling_needed",
        kind="noul",
        text="Does this project need horizontal scaling to handle its expected load?",
        depends_on=["expected_scale"],
    ))

    # Conditional: authentication approach – only when explicitly True.
    # (Previously asked whenever authentication wasn't False, so an
    # unaddressed/unknown authentication flag wrongly got a real question.)
    if req.authentication is True:
        questions.append(Question(
            id="auth_approach",
            kind="choice",
            text="Which authentication approach is most appropriate for this project?",
            options=["session cookies", "JWT", "third-party login"],
            depends_on=["authentication"],
        ))

    # Conditional: real-time transport – only when realtime is explicitly True.
    if req.realtime is True:
        questions.append(Question(
            id="realtime_transport",
            kind="choice",
            text="Which real-time transport mechanism best fits this project's requirements?",
            options=["polling", "WebSocket", "server-sent events"],
            depends_on=["realtime"],
        ))

    # Conditional: media storage – only when media_storage is explicitly True.
    if req.media_storage is True:
        questions.append(Question(
            id="media_storage_approach",
            kind="choice",
            text="Which media storage approach is most suitable for this project?",
            options=["object storage", "database blobs"],
            depends_on=["media_storage"],
        ))

    return questions
