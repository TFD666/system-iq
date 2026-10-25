import logging
import os

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .extraction import ExtractionError, extract_requirements
from .llm import GroqProvider, LLMProvider, RateLimitError
from .schemas import (
    DecisionMeta,
    DecisionResultOut,
    AlternativeOut,
    DesignRequest,
    DesignResponse,
)
from .decision.provider import (
    DecisionFormatError,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionUnavailableError,
    FakeDecisionProvider,
    JevProvider,
)
from .decision.questions import build_questions, build_state
from .decision.policy import apply_policy

# ── logging setup ──────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# ── app ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="SystemIQ Backend")

# Reject request bodies larger than 50 KB to prevent abuse
MAX_REQUEST_BODY_BYTES = 50 * 1024


@app.middleware("http")
async def enforce_body_size(request: Request, call_next):
    # Read Content-Length header; reject oversized payloads before parsing
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": "Request body too large (max 50 KB)."},
        )
    return await call_next(request)


# ── LLM dependency ─────────────────────────────────────────────────────────────

def get_provider() -> LLMProvider:
    """
    Build and return the LLM provider.
    A dependency function (not a module-level singleton) lets tests override
    this via app.dependency_overrides without patching globals.
    """
    return GroqProvider()


# ── Decision dependency ────────────────────────────────────────────────────────

# Maps the DECISION_PROVIDER env var to a provider label for fake-mode detection.
_FAKE_MODEL_LABEL = "fake (demo only)"


def get_decision_provider() -> DecisionProvider:
    """
    Return a DecisionProvider based on the DECISION_PROVIDER env variable.
    "jev" (default) uses the real Jev API; "fake" returns canned decisions.
    Tests override this via app.dependency_overrides.
    """
    mode = os.environ.get("DECISION_PROVIDER", "jev").lower()
    if mode == "fake":
        # FakeDecisionProvider never calls the network.
        return FakeDecisionProvider(model=_FAKE_MODEL_LABEL)
    return JevProvider()


# ── routes ─────────────────────────────────────────────────────────────────────

@app.post("/design", response_model=DesignResponse)
def design(
    request: DesignRequest,
    llm: LLMProvider = Depends(get_provider),
    decision_provider: DecisionProvider = Depends(get_decision_provider),
):
    """
    Accept a project idea and return extracted requirements plus architecture
    decisions. All heavy lifting happens in extraction.py and the decision
    provider; errors are translated to HTTP codes here.
    Provider is synchronous, so this is a plain def, not async def.
    """
    # ── Step 1: extract requirements from the idea ──────────────────────────
    try:
        requirements = extract_requirements(request.idea, llm)

    except RateLimitError:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit reached. Please wait a moment and try again."},
        )

    except ExtractionError as e:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Could not extract requirements from the idea: {e}"},
        )

    except (httpx.TimeoutException, httpx.NetworkError):
        return JSONResponse(
            status_code=504,
            content={"detail": "The AI provider did not respond in time. Please try again."},
        )

    # ── Step 2: build state and questions from requirements ─────────────────
    state = build_state(requirements)
    questions = build_questions(requirements)

    # Build a lookup so policy can find each question by id.
    question_map = {q.id: q for q in questions}

    # ── Step 3: call the decision provider ──────────────────────────────────
    try:
        result_set = decision_provider.decide(state, questions)

    except DecisionRateLimitError as e:
        if e.free_quota_exhausted:
            msg = (
                "Jev free quota reached; it resets daily around 05:30 IST. "
                "Try again later."
            )
        else:
            msg = (
                f"Decision service rate limit hit; "
                f"retry after {e.retry_after_seconds}s."
            )
        return JSONResponse(status_code=429, content={"detail": msg})

    except DecisionUnavailableError:
        return JSONResponse(
            status_code=504,
            content={"detail": "The decision service did not respond. Please try again."},
        )

    except DecisionFormatError:
        return JSONResponse(
            status_code=502,
            content={"detail": "The decision service returned an unexpected response."},
        )

    # ── Step 4: apply policy to every decision ───────────────────────────────
    decision_results = []
    for qid, raw_decision in result_set.decisions.items():
        q = question_map[qid]
        dr = apply_policy(q, raw_decision, requirements)
        decision_results.append(
            DecisionResultOut(
                id=dr.id,
                status=dr.status,
                choice=dr.choice,
                probability=dr.probability,
                top_alternatives=[
                    AlternativeOut(option=a.option, probability=a.probability)
                    for a in dr.top_alternatives
                ],
                based_on_unknowns=dr.based_on_unknowns,
            )
        )

    meta = DecisionMeta(
        decision_model=result_set.model,
        input_tokens=result_set.input_tokens,
        output_tokens=result_set.output_tokens,
    )

    return DesignResponse(
        stage="decided",
        requirements=requirements,
        decisions=decision_results,
        meta=meta,
    )
