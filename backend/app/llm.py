import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)

# Matches a <think>...</think> block some reasoning models leave in, even
# with reasoning_format="hidden". This is just a safety net.
_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    return _THINK_TAG_RE.sub("", text).strip()


# ── result type ────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


# ── custom errors ──────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    """
    Raised when Groq returns 429 and we give up: either retries are
    exhausted, or Groq asked us to wait longer than we're willing to block.
    retry_after_seconds is set in the second case so the caller can report
    a useful wait time (e.g. in the HTTP 429 response).
    """

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class GroqAuthError(Exception):
    """Raised when Groq rejects the API key (HTTP 401 or 403)."""


class LLMUnavailableError(Exception):
    """
    Raised when Groq keeps failing with a transient error (HTTP 500, 502,
    503, 504, a timeout, or a connection error) after retrying.
    """


# ── abstract base ──────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        """Call the model and return a JSON-mode result."""

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        """
        Call the model and return a free-form text result (no JSON mode).
        Not every provider needs this (only the design writer uses it), so
        it has a default instead of being an @abstractmethod -- that way
        existing providers that only do extraction don't have to implement it.
        """
        raise NotImplementedError("This provider does not support complete_text")


# ── Groq implementation ────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# How many times to retry after a 429 before giving up
MAX_RATE_LIMIT_RETRIES = 3

# Never block on one wait longer than this. If Groq asks for more than
# this, we fail fast with RateLimitError instead of sleeping.
MAX_RETRY_WAIT = 65

# Groq's 429 error message looks like:
#   "...Please try again in 14.7s." / "...in 2m5.3s." / "...in 1m."
# Group 1 is minutes (optional), group 2 is seconds (optional).
_RETRY_MESSAGE_RE = re.compile(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", re.IGNORECASE)

# Used when neither the Retry-After header nor the message text gives us
# a number -- not a "shorter fixed backoff" override, just a last resort.
_FALLBACK_RETRY_SECONDS = 10.0

# Used both as GroqProvider's default and as main.py's fallback when
# reporting which model was used, so the two never drift apart.
DEFAULT_GROQ_MODEL = "qwen/qwen3-27b"

# Transient failures (worth retrying): these HTTP statuses, plus any
# httpx timeout or connection error.
_TRANSIENT_STATUS_CODES = (500, 502, 503, 504)
MAX_TRANSIENT_RETRIES = 2
_TRANSIENT_WAIT_SCHEDULE = (5.0, 15.0)


def _parse_retry_seconds(response: httpx.Response) -> float:
    """
    How long Groq actually asked us to wait, in seconds.
    Prefers the Retry-After header; falls back to parsing the error
    message text (e.g. "try again in 14.7s", "2m5.3s", or "1m").
    Never returns or logs the message text itself -- only the number.
    """
    header = response.headers.get("retry-after")
    if header is not None:
        try:
            return float(header)
        except ValueError:
            pass  # header wasn't a plain number -- fall through to the message

    try:
        body = response.json()
        message = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
    except Exception:
        message = ""

    match = _RETRY_MESSAGE_RE.search(message)
    if match and (match.group(1) or match.group(2)):
        minutes = int(match.group(1)) if match.group(1) else 0
        seconds = float(match.group(2)) if match.group(2) else 0.0
        return minutes * 60 + seconds

    return _FALLBACK_RETRY_SECONDS


class GroqProvider(LLMProvider):
    def __init__(self, sleep=time.sleep) -> None:
        # Read credentials from environment; fail loudly at startup if missing
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        self._api_key = api_key
        self._model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
        # The design writer can use a different (e.g. higher-limit) model;
        # extraction always uses GROQ_MODEL.
        self._design_model = os.getenv("GROQ_DESIGN_MODEL", self._model)
        # Injectable so tests can verify the 5s/15s transient-retry wait
        # schedule without actually sleeping.
        self._sleep = sleep

    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        """
        Send a chat-completion request to Groq and return the result.

        Parameters confirmed from official Groq docs used here:
        - reasoning_format="hidden"  → strips <think> blocks server-side,
          saving tokens (doc: console.groq.com/docs/reasoning)
        - response_format={"type": "json_object"} → JSON mode; the prompt
          must mention JSON for this to work
          (doc: console.groq.com/docs/structured-outputs)
        - max_tokens → caps output length to stay within free-tier token budget
        """
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            # Hide the chain-of-thought so it doesn't eat into our token budget
            "reasoning_format": "hidden",
            # Force the model to output valid JSON
            "response_format": {"type": "json_object"},
        }
        return self._post_chat_completion(payload)

    def complete_text(self, system: str, user: str, max_tokens: int) -> LLMResult:
        """
        Same as complete_json, but no JSON mode -- used for free-form
        Markdown output (the design writer), not structured extraction.
        """
        payload = {
            "model": self._design_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "reasoning_format": "hidden",
            # No response_format here: we want Markdown prose, not JSON.
        }
        result = self._post_chat_completion(payload)
        # Safety net, same as extraction.py's stripping for complete_json.
        return LLMResult(
            text=_strip_think_tags(result.text),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    def _post_with_transient_retry(self, payload: dict, headers: dict) -> httpx.Response:
        """
        One logical request: retries HTTP 500/502/503/504, timeouts, and
        connection errors up to MAX_TRANSIENT_RETRIES times (5s then 15s),
        then raises LLMUnavailableError. Any other response (200, 429,
        401/403, ...) is returned as-is for the caller to handle.
        """
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                response = httpx.post(
                    GROQ_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=90.0,  # Groq reasoning calls can be slow
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < MAX_TRANSIENT_RETRIES:
                    wait = _TRANSIENT_WAIT_SCHEDULE[attempt]
                    # Exception class only in the log -- never its text.
                    logger.info(
                        "Groq %s: waiting %.0fs before attempt %d/%d",
                        type(exc).__name__, wait, attempt + 2, MAX_TRANSIENT_RETRIES + 1,
                    )
                    self._sleep(wait)
                    continue
                raise LLMUnavailableError(
                    "Groq did not respond after retrying transient errors."
                ) from exc

            if response.status_code not in _TRANSIENT_STATUS_CODES:
                return response

            if attempt < MAX_TRANSIENT_RETRIES:
                wait = _TRANSIENT_WAIT_SCHEDULE[attempt]
                # Status code and attempt number only -- never the response body.
                logger.info(
                    "Groq %d: waiting %.0fs before attempt %d/%d",
                    response.status_code, wait, attempt + 2, MAX_TRANSIENT_RETRIES + 1,
                )
                self._sleep(wait)
                continue
            raise LLMUnavailableError(
                f"Groq returned HTTP {response.status_code} and retries are exhausted."
            )

        raise LLMUnavailableError("Groq did not respond after retrying transient errors.")

    def _post_chat_completion(self, payload: dict) -> LLMResult:
        """
        The retry/error-handling loop shared by complete_json and
        complete_text. Only the payload (JSON mode or not) differs.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            response = self._post_with_transient_retry(payload, headers)

            if response.status_code == 429:
                requested = _parse_retry_seconds(response)

                if requested > MAX_RETRY_WAIT:
                    # Too long to block on -- fail fast instead of sleeping.
                    raise RateLimitError(
                        "Groq rate limit hit; requested wait is too long.",
                        retry_after_seconds=requested,
                    )

                wait = min(requested + 1, MAX_RETRY_WAIT)  # +1s buffer, never a shorter guess

                if attempt < MAX_RATE_LIMIT_RETRIES:
                    # Numbers only in the log -- never the error message text.
                    logger.info(
                        "Groq 429: waiting %.1fs before attempt %d/%d",
                        wait,
                        attempt + 1,
                        MAX_RATE_LIMIT_RETRIES,
                    )
                    time.sleep(wait)
                    continue  # Try again
                else:
                    raise RateLimitError(
                        "Groq rate limit hit and retries exhausted.",
                        retry_after_seconds=requested,
                    )

            if response.status_code in (401, 403):
                raise GroqAuthError(
                    f"Groq rejected the API key (HTTP {response.status_code})"
                )

            response.raise_for_status()

            data = response.json()
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            # Log token counts only — never log idea text or model output
            logger.info(
                "Groq call complete: prompt_tokens=%d, completion_tokens=%d",
                prompt_tokens,
                completion_tokens,
            )

            text = data["choices"][0]["message"]["content"]
            return LLMResult(
                text=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        # Should not be reachable, but satisfies the type checker
        raise RateLimitError("Groq rate limit hit and retries exhausted.")
