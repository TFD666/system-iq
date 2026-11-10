import json
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import (
    allowed_origin,
    demo_mode,
    is_hosted,
    max_idea_chars,
    redact_idea,
    samples_file,
)
from .hosted.access import (
    AccessManager,
    CapacityReached,
    CodeLimitReached,
    IPLimitReached,
)
from .hosted.jobs import JobManager, JobQueueFull
from .llm import GroqProvider, LLMProvider, LLMUnavailableError
from .schemas import (
    DecisionMeta,
    DesignRequest,
    DesignResponse,
    JobRequest,
    RevisionRoundOut,
    ValidateRequest,
    ValidationResultOut,
)
from .decision.provider import (
    DecisionProvider,
    FakeDecisionProvider,
    JevProvider,
    ReplayDecisionProvider,
)
from .pipeline import map_pipeline_error, run_pipeline, run_validation_loop

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
    except Exception as exc:
        status, msg = map_pipeline_error(exc, last_stage[0])
        return JSONResponse(status_code=status, content={"detail": msg})


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


# ── access-control dependency ─────────────────────────────────────────────────


def get_access_manager() -> AccessManager | None:
    if not is_hosted():
        return None
    if not hasattr(app.state, "access_manager"):
        app.state.access_manager = AccessManager()
    return app.state.access_manager


def _load_samples() -> list:
    path = samples_file()
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


# ── job manager dependency ────────────────────────────────────────────────────


def get_job_manager() -> JobManager:
    if not hasattr(app.state, "job_manager"):
        def _llm_factory() -> LLMProvider:
            return GroqProvider()

        def _decision_factory() -> DecisionProvider:
            mode = os.environ.get("DECISION_PROVIDER", "jev").lower()
            if mode == "fake":
                return FakeDecisionProvider(model=_FAKE_MODEL_LABEL)
            if mode == "replay":
                replay_file = os.environ.get("DECISION_REPLAY_FILE")
                if not replay_file:
                    raise ValueError("DECISION_REPLAY_FILE is not set")
                return ReplayDecisionProvider(replay_file)
            return JevProvider()

        app.state.job_manager = JobManager(
            llm_factory=_llm_factory,
            decision_factory=_decision_factory,
            redact=redact_idea if is_hosted() else None,
            access=get_access_manager(),
        )
    return app.state.job_manager


@app.post("/jobs")
def create_job(
    request: Request,
    body: JobRequest,
    manager: JobManager = Depends(get_job_manager),
    access: AccessManager | None = Depends(get_access_manager),
):
    hosted = is_hosted()
    code_label = None
    ip_hash = None

    if hosted:
        if access is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "Access control is not configured."},
            )
        raw_code = request.headers.get("x-access-code", "")
        code_label = access.check_code(raw_code)
        if code_label is None:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Invalid access code."
                    " See README for how to try System IQ.",
                },
            )
        ip_hash = access.client_ip(request)

    dm = demo_mode()
    if dm == "off":
        return JSONResponse(
            status_code=503,
            content={"detail": "Demo paused."},
        )
    if dm == "samples":
        return JSONResponse(
            status_code=200,
            content={
                "status": "sample",
                "sample": True,
                "reason": "samples mode",
                "samples": _load_samples(),
            },
        )

    limit = max_idea_chars()
    if len(body.idea) > limit:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Idea is too long (max {limit} characters)."},
        )

    token = None
    if hosted and access:
        try:
            token = access.reserve(code_label, ip_hash)
        except IPLimitReached:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Daily limit reached for this network."
                    " Try again tomorrow.",
                },
            )
        except CodeLimitReached:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Daily limit reached for this access code.",
                },
            )
        except CapacityReached as e:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "sample",
                    "sample": True,
                    "reason": e.reason,
                    "samples": _load_samples(),
                },
            )

    try:
        job_id, position = manager.submit(body.idea, token=token)
    except JobQueueFull:
        if token and access:
            access.release(token, app_failure=True)
        return JSONResponse(
            status_code=429,
            content={"detail": "Server busy, try in about 5 minutes."},
        )

    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "status": "queued", "position": position},
    )


@app.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
):
    job = manager.get(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Unknown or expired job."},
        )
    return job
