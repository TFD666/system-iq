import logging
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .design import TokenBudget, write_design
from .extraction import ExtractionError, extract_requirements
from .llm import DEFAULT_GROQ_MODEL, GroqAuthError, GroqProvider, LLMProvider, RateLimitError
from .schemas import (
    DecisionMeta,
    DecisionResultOut,
    AlternativeOut,
    DesignGroupStat,
    DesignRequest,
    DesignResponse,
    RevisionRoundOut,
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
from .decision.questions import build_questions, build_state
from .decision.policy import apply_policy
from .validation import (
    apply_validation_policy,
    build_validation_questions,
    build_validation_state,
    revise_sections,
    to_jev_questions,
)

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
    Construction errors (e.g. a missing API key) happen before the route body
    runs, so they are translated to HTTPException here rather than in design().
    """
    try:
        return GroqProvider()
    except EnvironmentError as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM service is misconfigured: {e}",
        )


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
    if mode == "replay":
        # ReplayDecisionProvider reads a saved file; never calls the network.
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

@app.post("/design", response_model=DesignResponse)
def design(
    request: DesignRequest,
    llm: LLMProvider = Depends(get_provider),
    decision_provider: DecisionProvider = Depends(get_decision_provider),
):
    """
    Accept a project idea and run the pipeline up to request.stage:
    "extract" -> requirements only, "decide" -> + architecture decisions,
    "design" -> + a written design document, "validate" (default) -> +
    a Jev-checked (and possibly revised) design document.
    All heavy lifting happens in extraction.py, the decision provider, and
    app/design/ and app/validation/; errors are translated to HTTP codes here.
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

    except (httpx.TimeoutException, httpx.NetworkError):
        return JSONResponse(
            status_code=504,
            content={"detail": "The AI provider did not respond in time. Please try again."},
        )

    if request.stage == "extract":
        return DesignResponse(stage="extracted", requirements=requirements)

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

    # ── Step 4: apply policy to every decision ───────────────────────────────
    decision_results = []
    for qid, raw_decision in result_set.decisions.items():
        q = question_map[qid]
        dr = apply_policy(q, raw_decision, requirements)
        decision_results.append(
            DecisionResultOut(
                id=dr.id,
                question=dr.question,
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

    meta_kwargs = dict(
        decision_model=result_set.model,
        input_tokens=result_set.input_tokens,
        output_tokens=result_set.output_tokens,
        decision_billing=result_set.billing_source,
        decision_cost=result_set.cost,
    )

    if request.stage == "decide":
        return DesignResponse(
            stage="decided",
            requirements=requirements,
            decisions=decision_results,
            meta=DecisionMeta(**meta_kwargs),
        )

    # ── Step 5: write the design document (stage == "design") ───────────────
    try:
        design_result = write_design(requirements, decision_results, llm, TokenBudget())

    except RateLimitError:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit reached while writing the design. Please wait a moment and try again."
            },
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

    meta_kwargs["llm_model"] = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    meta_kwargs["design_prompt_tokens"] = design_result.prompt_tokens
    meta_kwargs["design_completion_tokens"] = design_result.completion_tokens
    meta_kwargs["design_group_stats"] = [
        DesignGroupStat(
            id=stat.id,
            prompt_tokens=stat.prompt_tokens,
            completion_tokens=stat.completion_tokens,
            retries=stat.retries,
            elapsed_seconds=stat.elapsed_seconds,
        )
        for stat in design_result.group_stats
    ]

    if request.stage == "design":
        return DesignResponse(
            stage="designed",
            requirements=requirements,
            decisions=decision_results,
            meta=DecisionMeta(**meta_kwargs),
            design_markdown=design_result.markdown,
            design_warnings=design_result.warnings,
        )

    # ── Step 6: validate the design, revising flagged sections ──────────────
    # (stage == "validate", the default)
    design_warnings = list(design_result.warnings)
    current_markdown = design_result.markdown
    validation_results = []
    revision_rounds: list[dict] = []
    validation_calls = 0
    validation_input_tokens = 0
    validation_output_tokens = 0
    validation_status = "passed"
    revisions_done = 0
    budget = TokenBudget()

    validation_questions = build_validation_questions(requirements, decision_results)

    while validation_questions:
        try:
            state = build_validation_state(requirements, decision_results, current_markdown)
            result_set = decision_provider.decide(state, to_jev_questions(validation_questions))

        except DecisionRateLimitError:
            validation_status = "skipped"
            design_warnings.append("validation skipped: rate limited")
            break
        except DecisionAuthError:
            validation_status = "skipped"
            design_warnings.append("validation skipped: key rejected")
            break
        except (DecisionUnavailableError, DecisionFormatError):
            validation_status = "skipped"
            design_warnings.append("validation skipped: unavailable")
            break

        validation_calls += 1
        validation_input_tokens += result_set.input_tokens
        validation_output_tokens += result_set.output_tokens

        validation_results = [
            apply_validation_policy(q, result_set.decisions[q.id]) for q in validation_questions
        ]

        flagged = [r for r in validation_results if r.status == "flagged"]
        flagged_with_sections = [r for r in flagged if r.sections]
        for r in validation_results:
            if r.status == "possible" or (r.status == "flagged" and not r.sections):
                design_warnings.append(f"validation: {r.id}")

        if not flagged_with_sections or revisions_done >= request.max_revisions:
            validation_status = "flagged" if flagged else "passed"
            break

        new_markdown, revised_numbers, revise_warnings = revise_sections(
            current_markdown, flagged_with_sections, requirements, decision_results, llm, budget,
        )
        design_warnings.extend(revise_warnings)
        current_markdown = new_markdown
        revisions_done += 1
        revision_rounds.append({
            "round": revisions_done,
            "sections_revised": revised_numbers,
            "flagged_ids": [r.id for r in flagged_with_sections],
        })
        # Loop back: one more validation call to check the revised design.

    meta_kwargs["validation_calls"] = validation_calls
    meta_kwargs["validation_input_tokens"] = validation_input_tokens
    meta_kwargs["validation_output_tokens"] = validation_output_tokens
    meta_kwargs["validation_status"] = validation_status

    return DesignResponse(
        stage="validated",
        requirements=requirements,
        decisions=decision_results,
        meta=DecisionMeta(**meta_kwargs),
        design_markdown=current_markdown,
        design_warnings=design_warnings,
        validation=[
            ValidationResultOut(
                id=r.id, text=r.text, probability=r.probability,
                status=r.status, sections=r.sections,
            )
            for r in validation_results
        ],
        revisions=[RevisionRoundOut(**round_dict) for round_dict in revision_rounds],
    )
