"""
Reusable design pipeline: the same logic the /design endpoint runs,
callable from any context (HTTP handler, background worker, CLI).

Also contains run_validation_loop (shared by /design and /validate).

Exceptions propagate unchanged -- the caller maps them to HTTP codes
or whatever its transport needs.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Callable

import httpx

from .decision.policy import apply_policy
from .decision.provider import (
    DecisionAuthError,
    DecisionFormatError,
    DecisionProvider,
    DecisionRateLimitError,
    DecisionUnavailableError,
)
from .decision.questions import build_questions, build_state
from .design import TokenBudget, write_design
from .extraction import ExtractionError, extract_requirements
from .llm import DEFAULT_GROQ_MODEL, GroqAuthError, LLMProvider, LLMUnavailableError, RateLimitError
from .schemas import (
    AlternativeOut,
    DecisionMeta,
    DecisionResultOut,
    DesignGroupStat,
    DesignRequest,
    DesignResponse,
    RevisionRoundOut,
    ValidationResultOut,
)
from .validation import (
    ValidationStateTooLargeError,
    apply_validation_policy,
    build_validation_questions,
    build_validation_state,
    revise_sections,
    to_jev_questions,
)

logger = logging.getLogger(__name__)


# ── validation loop (shared by /design and /validate) ─────────────────────────


@dataclass
class ValidationRunResult:
    """Everything /design and /validate both need after running validation."""
    markdown: str
    warnings: list[str] = field(default_factory=list)
    results: list = field(default_factory=list)
    revision_rounds: list[dict] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = "passed"
    model: str | None = None


def run_validation_loop(
    requirements,
    decisions: list[DecisionResultOut] | None,
    design_markdown: str,
    max_revisions: int,
    llm: LLMProvider,
    decision_provider: DecisionProvider,
) -> ValidationRunResult:
    """
    Validate design_markdown against requirements/decisions, revising
    flagged sections up to max_revisions times.  Jev rate-limit/auth/
    unavailable errors stop the loop with status="skipped" and a warning.
    """
    run = ValidationRunResult(markdown=design_markdown)
    budget = TokenBudget()
    revisions_done = 0

    validation_questions = build_validation_questions(requirements, decisions)

    while validation_questions:
        try:
            state = build_validation_state(requirements, decisions, run.markdown)
            result_set = decision_provider.decide(state, to_jev_questions(validation_questions))

        except ValidationStateTooLargeError:
            run.status = "skipped"
            run.warnings.append("validation skipped: design too large")
            break
        except DecisionRateLimitError:
            run.status = "skipped"
            run.warnings.append("validation skipped: rate limited")
            break
        except DecisionAuthError:
            run.status = "skipped"
            run.warnings.append("validation skipped: key rejected")
            break
        except (DecisionUnavailableError, DecisionFormatError):
            run.status = "skipped"
            run.warnings.append("validation skipped: unavailable")
            break

        run.calls += 1
        run.input_tokens += result_set.input_tokens
        run.output_tokens += result_set.output_tokens
        run.model = result_set.model

        run.results = [
            apply_validation_policy(q, result_set.decisions[q.id]) for q in validation_questions
        ]

        flagged = [r for r in run.results if r.status == "flagged"]
        flagged_with_sections = [r for r in flagged if r.sections]
        for r in run.results:
            if r.status == "possible" or (r.status == "flagged" and not r.sections):
                run.warnings.append(f"validation: {r.id}")

        if not flagged_with_sections or revisions_done >= max_revisions:
            run.status = "flagged" if flagged else "passed"
            break

        new_markdown, revised_numbers, revise_warnings = revise_sections(
            run.markdown, flagged_with_sections, requirements, decisions, llm, budget,
        )
        run.warnings.extend(revise_warnings)
        run.markdown = new_markdown
        revisions_done += 1
        run.revision_rounds.append({
            "round": revisions_done,
            "sections_revised": revised_numbers,
            "flagged_ids": [r.id for r in flagged_with_sections],
        })

    return run


# ── stage callback ────────────────────────────────────────────────────────────

StageCallback = Callable[[str, dict | None], None]


def map_pipeline_error(exc: Exception, last_stage: str | None) -> tuple[int, str]:
    if isinstance(exc, RateLimitError):
        return 429, "Rate limit reached. Please wait a moment and try again."
    if isinstance(exc, ExtractionError):
        return 502, f"Could not extract requirements from the idea: {exc}"
    if isinstance(exc, GroqAuthError):
        return 502, (
            "LLM service rejected the API key. Check GROQ_API_KEY in "
            "backend/.env and restart the server."
        )
    if isinstance(exc, LLMUnavailableError):
        return 503, (
            "The language model service is temporarily unavailable. "
            "Try again in a few minutes."
        )
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return 504, "The AI provider did not respond in time. Please try again."
    if isinstance(exc, DecisionRateLimitError):
        if exc.free_quota_exhausted:
            return 429, (
                "Jev free quota reached; it resets daily around 05:30 IST. "
                "Try again later."
            )
        return 429, (
            f"Decision service rate limit hit; "
            f"retry after {exc.retry_after_seconds}s."
        )
    if isinstance(exc, DecisionAuthError):
        return 502, (
            "Decision service rejected the API key. Check OPENCODE_API_KEY "
            "in backend/.env and restart the server."
        )
    if isinstance(exc, DecisionUnavailableError):
        return 504, "The decision service did not respond. Please try again."
    if isinstance(exc, DecisionFormatError):
        return 502, "The decision service returned an unexpected response."
    logger.error("pipeline: unexpected error (%s)", type(exc).__name__)
    if last_stage == "validating":
        return 500, "Internal error during validation. Try again."
    return 500, "Internal error while writing the design. Try again."


def _fire(on_stage: StageCallback | None, name: str, detail: dict | None = None) -> None:
    if on_stage is None:
        return
    try:
        on_stage(name, detail)
    except Exception as exc:
        logger.info("on_stage callback raised %s", type(exc).__name__)


# ── pipeline ──────────────────────────────────────────────────────────────────


def run_pipeline(
    request: DesignRequest,
    llm: LLMProvider,
    decision_provider: DecisionProvider,
    on_stage: StageCallback | None = None,
    budget: TokenBudget | None = None,
) -> DesignResponse:
    """
    Run the /design pipeline up to request.stage.

    Exceptions (ExtractionError, RateLimitError, GroqAuthError,
    LLMUnavailableError, Decision*Error, httpx errors) propagate
    unchanged so the caller can map them to its own error codes.

    on_stage is called for each stage that actually runs.  A raising
    callback is swallowed (only the exception class name is logged).

    budget: share a TokenBudget across calls; None creates a fresh one.
    """
    if budget is None:
        budget = TokenBudget()

    # ── extract ────────────────────────────────────────────────────────
    _fire(on_stage, "extracting")
    requirements = extract_requirements(request.idea, llm)

    if request.stage == "extract":
        _fire(on_stage, "done")
        return DesignResponse(stage="extracted", requirements=requirements)

    # ── llm_only baseline ──────────────────────────────────────────────
    if request.mode == "llm_only":
        def _llm_only_group_cb(index: int, total: int) -> None:
            _fire(on_stage, "writing", {"group": index, "of": total})

        design_result = write_design(
            requirements, None, llm, budget, on_group=_llm_only_group_cb,
        )
        _fire(on_stage, "done")
        return DesignResponse(
            stage="designed",
            requirements=requirements,
            decisions=None,
            meta=DecisionMeta(
                decision_model="none (llm-only baseline)",
                input_tokens=0,
                output_tokens=0,
                llm_model=os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL),
                design_prompt_tokens=design_result.prompt_tokens,
                design_completion_tokens=design_result.completion_tokens,
                design_group_stats=[
                    DesignGroupStat(
                        id=stat.id,
                        prompt_tokens=stat.prompt_tokens,
                        completion_tokens=stat.completion_tokens,
                        retries=stat.retries,
                        elapsed_seconds=stat.elapsed_seconds,
                        retry_reasons=stat.retry_reasons,
                    )
                    for stat in design_result.group_stats
                ],
            ),
            design_markdown=design_result.markdown,
            design_warnings=design_result.warnings,
        )

    # ── decide ─────────────────────────────────────────────────────────
    _fire(on_stage, "deciding")
    state = build_state(requirements)
    questions = build_questions(requirements)
    question_map = {q.id: q for q in questions}

    result_set = decision_provider.decide(state, questions)

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
        _fire(on_stage, "done")
        return DesignResponse(
            stage="decided",
            requirements=requirements,
            decisions=decision_results,
            meta=DecisionMeta(**meta_kwargs),
        )

    # ── design ─────────────────────────────────────────────────────────
    def _group_cb(index: int, total: int) -> None:
        _fire(on_stage, "writing", {"group": index, "of": total})

    design_result = write_design(
        requirements, decision_results, llm, budget,
        writer_style=request.writer_style, on_group=_group_cb,
    )

    meta_kwargs["llm_model"] = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    meta_kwargs["writer_style"] = request.writer_style
    meta_kwargs["design_prompt_tokens"] = design_result.prompt_tokens
    meta_kwargs["design_completion_tokens"] = design_result.completion_tokens
    meta_kwargs["design_group_stats"] = [
        DesignGroupStat(
            id=stat.id,
            prompt_tokens=stat.prompt_tokens,
            completion_tokens=stat.completion_tokens,
            retries=stat.retries,
            elapsed_seconds=stat.elapsed_seconds,
            retry_reasons=stat.retry_reasons,
        )
        for stat in design_result.group_stats
    ]

    if request.stage == "design":
        _fire(on_stage, "done")
        return DesignResponse(
            stage="designed",
            requirements=requirements,
            decisions=decision_results,
            meta=DecisionMeta(**meta_kwargs),
            design_markdown=design_result.markdown,
            design_warnings=design_result.warnings,
        )

    # ── validate ───────────────────────────────────────────────────────
    _fire(on_stage, "validating")
    run = run_validation_loop(
        requirements, decision_results, design_result.markdown,
        request.max_revisions, llm, decision_provider,
    )

    meta_kwargs["validation_calls"] = run.calls
    meta_kwargs["validation_input_tokens"] = run.input_tokens
    meta_kwargs["validation_output_tokens"] = run.output_tokens
    meta_kwargs["validation_status"] = run.status
    meta_kwargs["validation_model"] = run.model

    _fire(on_stage, "done")
    return DesignResponse(
        stage="validated",
        requirements=requirements,
        decisions=decision_results,
        meta=DecisionMeta(**meta_kwargs),
        design_markdown=run.markdown,
        design_warnings=design_result.warnings + run.warnings,
        validation=[
            ValidationResultOut(
                id=r.id, text=r.text, probability=r.probability,
                status=r.status, sections=r.sections,
            )
            for r in run.results
        ],
        revisions=[RevisionRoundOut(**round_dict) for round_dict in run.revision_rounds],
    )
