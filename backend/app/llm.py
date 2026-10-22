import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)


# ── result type ────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


# ── custom errors ──────────────────────────────────────────────────────────────

class RateLimitError(Exception):
    """Raised when Groq returns 429 and retries are exhausted."""


# ── abstract base ──────────────────────────────────────────────────────────────

class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str, max_tokens: int) -> LLMResult:
        """Call the model and return a JSON-mode result."""


# ── Groq implementation ────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# How many times to retry after a 429 before giving up
MAX_RATE_LIMIT_RETRIES = 2

# Maximum seconds to wait on a single 429 retry-after header
MAX_RETRY_WAIT = 60


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        # Read credentials from environment; fail loudly at startup if missing
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        self._api_key = api_key
        self._model = os.getenv("GROQ_MODEL", "qwen/qwen3-27b")

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

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = httpx.post(
                    GROQ_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=90.0,  # Groq reasoning calls can be slow
                )
            except httpx.TimeoutException:
                raise  # Let the caller (main.py) translate this to HTTP 504
            except httpx.NetworkError:
                raise  # Same — let the caller handle it

            if response.status_code == 429:
                # Respect the Retry-After header; default to 10 s if missing
                retry_after = int(response.headers.get("retry-after", 10))
                wait = min(retry_after, MAX_RETRY_WAIT)

                if attempt < MAX_RATE_LIMIT_RETRIES:
                    time.sleep(wait)
                    continue  # Try again
                else:
                    raise RateLimitError(
                        "Groq rate limit hit and retries exhausted."
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
