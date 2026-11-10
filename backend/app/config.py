"""
Environment-based configuration helpers.

Every function reads os.environ at CALL time (never at import time)
so tests can monkeypatch freely.
"""

import os

from .redact import redact

_HOSTED_DEFAULT_MAX_IDEA = 2000
_LOCAL_DEFAULT_MAX_IDEA = 20_000


def is_hosted() -> bool:
    return os.environ.get("HOSTED") == "1"


def allowed_origin() -> str | None:
    return os.environ.get("ALLOWED_ORIGIN") or None


def max_idea_chars() -> int:
    explicit = os.environ.get("MAX_IDEA_CHARS")
    if explicit is not None:
        return int(explicit)
    return _HOSTED_DEFAULT_MAX_IDEA if is_hosted() else _LOCAL_DEFAULT_MAX_IDEA


def redact_idea(text: str) -> tuple[str, list[tuple[str, int]]]:
    """Redact sensitive content from idea text before model calls."""
    return redact(text)


_VALID_DEMO_MODES = {"live", "llm_only", "samples", "off"}


def demo_mode() -> str:
    val = os.environ.get("DEMO_MODE", "live").lower()
    return val if val in _VALID_DEMO_MODES else "live"
