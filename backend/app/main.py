import logging

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .extraction import ExtractionError, extract_requirements
from .llm import GroqProvider, LLMProvider, RateLimitError
from .schemas import DesignRequest, DesignResponse

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


# ── dependency ─────────────────────────────────────────────────────────────────

def get_provider() -> LLMProvider:
    """
    Build and return the LLM provider.
    Using a dependency function (instead of a module-level singleton) lets
    tests override this via app.dependency_overrides without patching globals.
    A missing API key fails on the first request rather than at import time,
    which makes the test client importable without setting env vars.
    """
    return GroqProvider()


# ── routes ─────────────────────────────────────────────────────────────────────

@app.post("/design", response_model=DesignResponse)
async def design(request: DesignRequest, provider: LLMProvider = Depends(get_provider)):
    """
    Accept a project idea and return extracted requirements.
    All heavy lifting happens in extraction.py; errors are translated here.
    """
    try:
        requirements = extract_requirements(request.idea, provider)

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

    return DesignResponse(stage="extracted", requirements=requirements)
