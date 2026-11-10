import logging
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import allowed_origin, is_hosted, max_idea_chars
from .extraction import ExtractionError
from .llm import GroqAuthError, GroqProvider, LLMProvider, LLMUnavailableError, RateLimitError
from .schemas import (
    DecisionMeta,
    DesignRequest,
    DesignResponse,
    RevisionRoundOut,
    ValidateRequest,
    ValidationResultOut,
)
from .decision.provider import (
    DecisionAuthError,
    DecisionFormatError,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionUnavailableError,
    FakeDecisionProvider,
    JevProvider,
    ReplayDecisionProvider,
)
from .pipeline import run_pipeline, run_validation_loop

# ── logging setup ──────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# ── app ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="SystemIQ Backend")

MAX_REQUEST_BODY_BYTES = 50 * 1024
MAX_VALIDATE_BODY_BYTES = 100 * 1024

_HOSTED_BLOCKED_PATHS = {"/design", "/validate"}


@app.middleware("http")
async def dynamic_cors(request: Request, call_next):
    origin = allowed_origin()
    req_origin = request.headers.get("origin")
    match = origin is not None and req_origin == origin

    if request.method == "OPTIONS" and match:
        return JSONResponse(
            content=None, status_code=200,
            headers={
                "access-control-allow-origin": origin,
                "access-control-allow-methods": "GET, POST",
                "access-control-allow-headers": "Content-Type, X-Access-Code",
            },
        )

    response = await call_next(request)

    if match:
        response.headers["access-control-allow-origin"] = origin
        response.headers["access-control-allow-methods"] = "GET, POST"
        response.headers["access-control-allow-headers"] = "Content-Type, X-Access-Code"

    return response


@app.middleware("http")
async def enforce_body_size(request: Request, call_next):
    limit = MAX_VALIDATE_BODY_BYTES if request.url.path == "/validate" else MAX_REQUEST_BODY_BYTES
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > limit:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large (max {limit // 1024} KB)."},
        )
    return await call_next(request)


@app.middleware("http")
async def hosted_guard(request: Request, call_next):
    if is_hosted() and request.method == "POST" and request.url.path in _HOSTED_BLOCKED_PATHS:
        return JSONResponse(status_code=404, content={"detail": "Not available on this server."})
    return await call_next(request)


# ── LLM dependency ─────────────────────────────────────────────────────────────

def get_provider() -> LLMProvider:
    try:
        return GroqProvider()
    except EnvironmentError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM service is misconfigured: {e}",
        )


# ── Decision dependency ────────────────────────────────────────────────────────

_FAKE_MODEL_LABEL = "fake (demo only)"

_LLM_UNAVAILABLE_DETAIL = "The language model service is temporarily unavailable. Try again in a few minutes."


def get_decision_provider() -> DecisionProvider:
    mode = os.environ.get("DECISION_PROVIDER", "jev").lower()
    if mode == "fake":
        return FakeDecisionProvider(model=_FAKE_MODEL_LABEL)
    if mode == "replay":
        replay_file = os.environ.get("DECISION_REPLAY_FILE")
        if not replay_file:
            raise HTTPException(
                status_code=503,
                detail="Decision service is misconfigured: DECISION_REPLAY_FILE is not set.",
            )
        try:
            return ReplayDecisionProvider(replay_file)
        except (OSError, ValueError) as e:
            raise HTTPException(
                status_code=503,
                detail=f"Decision service is misconfigured: could not read the replay file ({type(e).__name__}).",
            )
    try:
        return JevProvider()
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Decision service is misconfigured: {e}",
        )


# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok", "hosted": is_hosted()}


@app.post("/design", response_model=DesignResponse)
def design(
    request: DesignRequest,
    llm: LLMProvider = Depends(get_provider),
    decision_provider: DecisionProvider = Depends(get_decision_provider),
):
    limit = max_idea_chars()
    if len(request.idea) > limit:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Idea is too long (max {limit} characters)."},
        )

    last_stage = [None]

    def _track_stage(name, detail):
        last_stage[0] = name

    try:
        return run_pipeline(request, llm, decision_provider, on_stage=_track_stage)

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

    except GroqAuthError:
        return JSONResponse(
            status_code=502,
            content={
                "detail": (
                    "LLM service rejected the API key. Check GROQ_API_KEY in "
                    "backend/.env and restart the server."
                )
            },
        )

    except LLMUnavailableError:
        return JSONResponse(status_code=503, content={"detail": _LLM_UNAVAILABLE_DETAIL})

    except (httpx.TimeoutException, httpx.NetworkError):
        return JSONResponse(
            status_code=504,
            content={"detail": "The AI provider did not respond in time. Please try again."},
        )

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

    except DecisionAuthError:
        return JSONResponse(
            status_code=502,
            content={
                "detail": (
                    "Decision service rejected the API key. Check OPENCODE_API_KEY "
                    "in backend/.env and restart the server."
                )
            },
        )

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

    except Exception as e:
        logger.error("design: unexpected error (%s)", type(e).__name__)
        if last_stage[0] == "validating":
            msg = "Internal error during validation. Try again."
        else:
            msg = "Internal error while writing the design. Try again."
        return JSONResponse(status_code=500, content={"detail": msg})


@app.post("/validate", response_model=DesignResponse)
def validate_design(
    request: ValidateRequest,
    llm: LLMProvider = Depends(get_provider),
    decision_provider: DecisionProvider = Depends(get_decision_provider),
):
    try:
        run = run_validation_loop(
            request.requirements, request.decisions, request.design_markdown,
            request.max_revisions, llm, decision_provider,
        )
    except LLMUnavailableError:
        return JSONResponse(status_code=503, content={"detail": _LLM_UNAVAILABLE_DETAIL})
    except Exception as e:
        logger.error("validate: unexpected error during validation (%s)", type(e).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal error during validation. Try again."},
        )

    meta = DecisionMeta(
        decision_model="n/a (validation only)",
        input_tokens=0,
        output_tokens=0,
        validation_calls=run.calls,
        validation_input_tokens=run.input_tokens,
        validation_output_tokens=run.output_tokens,
        validation_status=run.status,
        validation_model=run.model,
    )

    return DesignResponse(
        stage="validated",
        requirements=request.requirements,
        decisions=request.decisions,
        meta=meta,
        design_markdown=run.markdown,
        design_warnings=run.warnings,
        validation=[
            ValidationResultOut(
                id=r.id, text=r.text, probability=r.probability,
                status=r.status, sections=r.sections,
            )
            for r in run.results
        ],
        revisions=[RevisionRoundOut(**round_dict) for round_dict in run.revision_rounds],
    )
