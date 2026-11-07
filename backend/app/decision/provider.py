"""
Decision provider – asks a Jev (TypeSafe System One) model structured
questions about a piece of state and returns typed answers.

Endpoint proven to work:
    POST https://opencode.ai/inference/systemone/v1/systemone
Auth:
    Authorization: Bearer <OPENCODE_API_KEY>

Response field assumptions (from https://docs.typesafe.ai/api/system-one):
    Noul  -> {"type":"noul", "noul": float}
             noul = probability of "yes" (confirmed: 0.97 in live probe).
    Choice-> {"type":"choice", "choice": str, "confidence": float,
              "probabilities": {option: float, ...}}
             Confirmed from live probe (eval/results/jev_choice_probe.json).
    Score -> {"type":"score", "score": float, "confidence": float,
              "legend": {"0": str, ...}, "probabilities": {"0": float, ...}}
             Assumed from docs – NOT yet confirmed with a live call.

Usage block may contain extra keys (e.g. opencode.billing_source, cost).
We read the ones we need and ignore the rest.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Question(BaseModel):
    """A single structured question to send to the decision model."""

    id: str
    kind: str  # "noul" | "choice" | "score"
    text: str  # becomes "instructions" in the API payload
    options: list[str] | None = None  # required for choice and score
    depends_on: list[str] = Field(default_factory=list)  # used by app layer, not by the API


class Alternative(BaseModel):
    """One possible answer and its probability."""

    option: str
    probability: float


class Decision(BaseModel):
    """
    Parsed answer for one question.

    For noul:
        probability = probability of "yes" (the noul value).
        choice = None.
        confidence = None (noul answers don't include confidence).
    For choice:
        probability = probability of the selected choice.
        choice = the selected option name.
        confidence = model's reported confidence.
    For score:
        probability = expected score normalised to 0..1
                      (raw_score / (num_levels - 1)).
        choice = description of the most-probable level.
        confidence = model's reported confidence.
    """

    id: str
    kind: str
    choice: str | None = None
    probability: float
    alternatives: list[Alternative] = Field(default_factory=list)
    confidence: float | None = None


class DecisionResultSet(BaseModel):
    """The full set of answers from one API call."""

    decisions: dict[str, Decision]
    model: str
    input_tokens: int
    output_tokens: int
    # Billing info read from usage.opencode.billing_source (None when absent).
    billing_source: str | None = None
    # Actual cost read from usage.cost (None when absent).
    cost: float | None = None


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class DecisionRateLimitError(Exception):
    """The API returned 429.  Callers should show a friendly message."""

    def __init__(
        self,
        retry_after_seconds: int,
        free_quota_exhausted: bool = False,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        self.free_quota_exhausted = free_quota_exhausted
        super().__init__(
            f"Rate-limited; retry after {retry_after_seconds}s"
            + (" (free quota exhausted)" if free_quota_exhausted else "")
        )


class DecisionUnavailableError(Exception):
    """Network error or timeout – the API could not be reached."""

    pass


class DecisionFormatError(Exception):
    """Response JSON was malformed, missing an expected question, or
    contained a probability outside 0..1."""

    pass


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class DecisionProvider(abc.ABC):
    """Interface every decision back-end must implement."""

    @abc.abstractmethod
    def decide(
        self,
        state: dict[str, Any],
        questions: list[Question],
    ) -> DecisionResultSet:
        """Evaluate *questions* against *state* and return typed decisions."""
        ...


# ---------------------------------------------------------------------------
# Jev (TypeSafe System One) provider
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = (
    "https://opencode.ai/inference/systemone/v1/systemone"
)
_DEFAULT_MODEL = "jev-1.13-free"
_TIMEOUT_SECONDS = 30
_MAX_RETRIES_ON_SHORT_429 = 2  # retry at most twice for short retry-after
_SHORT_RETRY_THRESHOLD = 60    # seconds – anything above this is "long"

# Models that don't end with "-free" cost real money.
# Block them unless the operator explicitly opts in.
_FREE_MODEL_SUFFIX = "-free"
_ALLOW_PAID_ENV = "ALLOW_PAID_JEV"


class JevProvider(DecisionProvider):
    """Calls the Jev System One endpoint over HTTP (synchronous)."""

    def __init__(self) -> None:
        self._base_url = os.environ.get("JEV_BASE_URL", _DEFAULT_BASE_URL)
        self._model = os.environ.get("JEV_MODEL", _DEFAULT_MODEL)
        self._api_key = os.environ.get("OPENCODE_API_KEY", "")

        if not self._api_key:
            raise ValueError(
                "OPENCODE_API_KEY must be set in the environment"
            )

        # Cost guard: refuse to start with a paid model unless explicitly allowed.
        if not self._model.endswith(_FREE_MODEL_SUFFIX):
            allow_paid = os.environ.get(_ALLOW_PAID_ENV, "").lower()
            if allow_paid != "true":
                raise ValueError(
                    f"JEV_MODEL '{self._model}' does not end with '-free'. "
                    "Paid models are blocked by default. "
                    f"Set {_ALLOW_PAID_ENV}=true to allow paid model usage."
                )

    # -- public interface ---------------------------------------------------

    def decide(
        self,
        state: dict[str, Any],
        questions: list[Question],
    ) -> DecisionResultSet:
        # State is sent as compact JSON text, as proven in earlier probes.
        state_text = json.dumps(state, separators=(",", ":"))

        # Build the questions map the API expects.
        questions_map = self._build_questions_map(questions)

        payload: dict[str, Any] = {
            "model": self._model,
            "state": state_text,
            "questions": questions_map,
        }

        body = self._post_with_retry(payload)
        return self._parse_response(body, questions)

    # -- request helpers ----------------------------------------------------

    @staticmethod
    def _build_questions_map(
        questions: list[Question],
    ) -> dict[str, dict[str, Any]]:
        """Convert our Question list into the API's questions dict."""
        out: dict[str, dict[str, Any]] = {}
        for q in questions:
            entry: dict[str, Any] = {
                "type": q.kind,
                "instructions": q.text,
            }
            if q.kind == "choice" and q.options:
                # Choice criteria: {option_name: option_name}
                # (option is its own description, as specified in the task)
                entry["criteria"] = {opt: opt for opt in q.options}
            elif q.kind == "score" and q.options:
                # Score criteria: ordered list of level descriptions
                entry["criteria"] = list(q.options)
            out[q.id] = entry
        return out

    def _post_with_retry(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST to Jev with automatic retry on short 429s."""
        attempt = 0
        while True:
            try:
                resp = httpx.post(
                    self._base_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=_TIMEOUT_SECONDS,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                # Never include the URL (it might leak in logs).
                raise DecisionUnavailableError(
                    "Could not reach the decision service"
                ) from exc

            if resp.status_code == 429:
                self._handle_429(resp, attempt)
                # _handle_429 only returns if we should retry.
                retry_after = self._parse_retry_after(resp)
                attempt += 1
                time.sleep(retry_after)
                continue

            if resp.status_code != 200:
                # Log only the status code – never the body or URL.
                logger.warning(
                    "Jev returned HTTP %d", resp.status_code
                )
                raise DecisionUnavailableError(
                    f"Decision service returned HTTP {resp.status_code}"
                )

            try:
                return resp.json()  # type: ignore[no-any-return]
            except Exception as exc:
                raise DecisionFormatError(
                    "Response was not valid JSON"
                ) from exc

    # -- 429 handling -------------------------------------------------------

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> int:
        """Read the retry-after header, default to 1 if missing."""
        raw = resp.headers.get("retry-after", "1")
        try:
            return int(raw)
        except ValueError:
            return 1

    def _handle_429(
        self,
        resp: httpx.Response,
        attempt: int,
    ) -> None:
        """Decide whether to retry or raise on a 429.

        Rules:
        - retry-after > 60s  -> raise immediately (don't waste time waiting)
        - FreeUsageLimitError -> raise with free_quota_exhausted=True
        - retry-after <= 60s and attempts left -> return (caller retries)
        - retry-after <= 60s but no attempts left -> raise
        """
        retry_after = self._parse_retry_after(resp)

        # Check for the free-quota error type in the body.
        free_exhausted = False
        try:
            body = resp.json()
            error_type = (
                body.get("error", {}).get("type", "")
                if isinstance(body, dict)
                else ""
            )
            free_exhausted = error_type == "FreeUsageLimitError"
        except Exception:
            pass

        # Long wait or free quota exhausted -> raise at once.
        if retry_after > _SHORT_RETRY_THRESHOLD or free_exhausted:
            raise DecisionRateLimitError(
                retry_after_seconds=retry_after,
                free_quota_exhausted=free_exhausted,
            )

        # Too many retries already -> raise.
        if attempt >= _MAX_RETRIES_ON_SHORT_429:
            raise DecisionRateLimitError(
                retry_after_seconds=retry_after,
                free_quota_exhausted=False,
            )

        # Otherwise: caller will sleep and retry.
        # Log only the retry count and wait time – no state or question text.
        logger.info(
            "Jev 429: retry-after=%ds attempt=%d/%d",
            retry_after,
            attempt + 1,
            _MAX_RETRIES_ON_SHORT_429,
        )

    # -- response parsing ---------------------------------------------------

    def _parse_response(
        self,
        body: dict[str, Any],
        questions: list[Question],
    ) -> DecisionResultSet:
        """Turn the raw JSON into a DecisionResultSet.

        Validates:
        - every question id has an answer
        - answer type matches question kind
        - probabilities are in 0..1

        The usage block may contain extra vendor keys (e.g. opencode.*).
        We only read the fields we know about; unknown keys are ignored.
        """
        if not isinstance(body, dict):
            raise DecisionFormatError("Response is not a JSON object")

        answers_raw = body.get("answers")
        if not isinstance(answers_raw, dict):
            raise DecisionFormatError("Response missing 'answers' dict")

        # answers_raw is keyed by question id; order may differ from question list.
        usage = body.get("usage", {}) if isinstance(body.get("usage"), dict) else {}

        # Read the top-level token counts (always present in valid responses).
        input_tokens: int = usage.get("input_tokens", 0)
        output_tokens: int = usage.get("output_tokens", 0)

        # Read optional cost and billing_source; ignore if absent or wrong type.
        raw_cost = usage.get("cost")
        cost: float | None = float(raw_cost) if raw_cost is not None else None

        # billing_source lives one level deeper: usage.opencode.billing_source
        opencode_block = usage.get("opencode", {})
        billing_source: str | None = None
        if isinstance(opencode_block, dict):
            bs = opencode_block.get("billing_source")
            billing_source = str(bs) if bs is not None else None

        # Warn if money was spent or the billing source is not "free".
        if (cost is not None and cost > 0) or (
            billing_source is not None and billing_source != "free"
        ):
            logger.warning(
                "Jev response indicates potential cost: cost=%s billing_source=%s",
                cost,
                billing_source,
            )

        # Log token counts only – safe to log.
        logger.debug(
            "Jev usage: input_tokens=%d output_tokens=%d",
            input_tokens,
            output_tokens,
        )

        decisions: dict[str, Decision] = {}
        for q in questions:
            raw = answers_raw.get(q.id)
            if raw is None:
                raise DecisionFormatError(
                    f"Answer missing for question '{q.id}'"
                )
            # Verify the type matches.
            if raw.get("type") != q.kind:
                raise DecisionFormatError(
                    f"Answer type '{raw.get('type')}' does not match "
                    f"question kind '{q.kind}' for '{q.id}'"
                )
            decisions[q.id] = self._parse_answer(q, raw)

        return DecisionResultSet(
            decisions=decisions,
            model=body.get("model", self._model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            billing_source=billing_source,
            cost=cost,
        )

    def _parse_answer(
        self,
        question: Question,
        raw: dict[str, Any],
    ) -> Decision:
        """Parse one answer dict into a Decision."""
        kind = question.kind

        if kind == "noul":
            return self._parse_noul(question, raw)
        elif kind == "choice":
            return self._parse_choice(question, raw)
        elif kind == "score":
            return self._parse_score(question, raw)
        else:
            raise DecisionFormatError(f"Unknown answer type '{kind}'")

    def _parse_noul(
        self,
        question: Question,
        raw: dict[str, Any],
    ) -> Decision:
        """Parse a noul answer.

        Docs shape:  {"type": "noul", "noul": 0.98}
        noul = probability of "yes" (confirmed with live probe).
        """
        noul_value = raw.get("noul")
        if noul_value is None:
            raise DecisionFormatError(
                f"Noul answer for '{question.id}' missing 'noul' field"
            )
        prob = float(noul_value)
        self._validate_probability(prob, question.id, "noul")
        return Decision(
            id=question.id,
            kind="noul",
            choice=None,
            probability=prob,
            alternatives=[],
            confidence=None,  # noul answers have no confidence field
        )

    def _parse_choice(
        self,
        question: Question,
        raw: dict[str, Any],
    ) -> Decision:
        """Parse a choice answer.

        Confirmed live shape (from eval/results/jev_choice_probe.json):
            {
                "type": "choice",
                "choice": "PostgreSQL + PostGIS",   # winning option
                "confidence": 0.96,                 # 0..1
                "probabilities": {                  # one entry per criterion
                    "PostgreSQL": 0,
                    "DynamoDB": 0.01,
                    "MongoDB": 0.02,
                    "PostgreSQL + PostGIS": 0.97
                }
            }
        """
        selected = raw.get("choice")
        if selected is None:
            raise DecisionFormatError(
                f"Choice answer for '{question.id}' missing 'choice' field"
            )

        probabilities: dict[str, float] = raw.get("probabilities", {})
        confidence = raw.get("confidence")

        # Probability of the selected choice.
        prob = float(probabilities.get(selected, 0.0))
        self._validate_probability(prob, question.id, "choice")

        # Build alternatives list from probabilities.
        alts = [
            Alternative(option=opt, probability=float(p))
            for opt, p in probabilities.items()
        ]
        for alt in alts:
            self._validate_probability(
                alt.probability, question.id, f"choice alt '{alt.option}'"
            )

        return Decision(
            id=question.id,
            kind="choice",
            choice=str(selected),
            probability=prob,
            alternatives=alts,
            confidence=float(confidence) if confidence is not None else None,
        )

    def _parse_score(
        self,
        question: Question,
        raw: dict[str, Any],
    ) -> Decision:
        """Parse a score answer.

        Docs shape (assumed, not yet confirmed with a live call):
            {
                "type": "score",
                "score": 1.7,            # expected value (0..N-1)
                "confidence": 0.55,      # 0..1
                "legend": {"0": "Can wait", "1": "...", "2": "..."},
                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}
            }

        We normalise the raw score to 0..1 by dividing by (num_levels - 1),
        so it fits the Decision.probability contract.
        """
        raw_score = raw.get("score")
        if raw_score is None:
            raise DecisionFormatError(
                f"Score answer for '{question.id}' missing 'score' field"
            )

        legend: dict[str, str] = raw.get("legend", {})
        probabilities: dict[str, float] = raw.get("probabilities", {})
        confidence = raw.get("confidence")

        # Normalise score to 0..1.
        num_levels = max(len(legend), len(probabilities), 1)
        max_index = max(num_levels - 1, 1)  # avoid division by zero
        normalised = float(raw_score) / max_index
        # Clamp to 0..1 in case of rounding.
        normalised = max(0.0, min(1.0, normalised))

        # The "choice" is the description of the most-probable level.
        best_level = (
            max(probabilities, key=lambda k: probabilities[k])
            if probabilities
            else None
        )
        choice_text = legend.get(best_level, best_level) if best_level else None

        # Build alternatives from legend + probabilities.
        alts: list[Alternative] = []
        for level_key, desc in legend.items():
            p = float(probabilities.get(level_key, 0.0))
            self._validate_probability(
                p, question.id, f"score level '{level_key}'"
            )
            alts.append(Alternative(option=desc, probability=p))

        return Decision(
            id=question.id,
            kind="score",
            choice=str(choice_text) if choice_text else None,
            probability=normalised,
            alternatives=alts,
            confidence=float(confidence) if confidence is not None else None,
        )

    # -- validation ---------------------------------------------------------

    @staticmethod
    def _validate_probability(
        value: float,
        question_id: str,
        label: str,
    ) -> None:
        """Raise if a probability is outside [0, 1]."""
        if not (0.0 <= value <= 1.0):
            raise DecisionFormatError(
                f"Probability {value} for {label} in '{question_id}' "
                f"is outside 0..1"
            )


# ---------------------------------------------------------------------------
# Fake provider for tests
# ---------------------------------------------------------------------------


class FakeDecisionProvider(DecisionProvider):
    """Returns pre-loaded decisions without calling any API.

    Usage in tests:
        fake = FakeDecisionProvider(canned={
            "q1": Decision(id="q1", kind="noul", probability=0.9),
        })
        result = fake.decide({}, questions)
    """

    def __init__(
        self,
        canned: dict[str, Decision] | None = None,
        model: str = "fake-model",
        billing_source: str | None = None,
        cost: float | None = None,
    ) -> None:
        self._canned = canned or {}
        self._model = model
        self._billing_source = billing_source
        self._cost = cost

    def decide(
        self,
        state: dict[str, Any],
        questions: list[Question],
    ) -> DecisionResultSet:
        decisions: dict[str, Decision] = {}
        for q in questions:
            if q.id in self._canned:
                decisions[q.id] = self._canned[q.id]
            else:
                # Sensible default: noul with 50 % probability.
                decisions[q.id] = Decision(
                    id=q.id,
                    kind=q.kind,
                    probability=0.5,
                )
        return DecisionResultSet(
            decisions=decisions,
            model=self._model,
            input_tokens=0,
            output_tokens=0,
            billing_source=self._billing_source,
            cost=self._cost,
        )
