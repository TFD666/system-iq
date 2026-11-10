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


def access_codes() -> list[tuple[str, str, int]]:
    """Parse ACCESS_CODES='label:code:daily_limit,...' from env."""
    raw = os.environ.get("ACCESS_CODES", "")
    if not raw.strip():
        return []
    entries: list[tuple[str, str, int]] = []
    for part in raw.split(","):
        pieces = part.strip().split(":")
        if len(pieces) != 3:
            continue
        label, code, limit_str = pieces
        label, code = label.strip(), code.strip()
        if not label or not code:
            continue
        try:
            entries.append((label, code, int(limit_str.strip())))
        except ValueError:
            continue
    return entries


def daily_design_cap() -> int:
    return int(os.environ.get("DAILY_DESIGN_CAP", "8"))


def ip_daily_limit() -> int:
    return int(os.environ.get("IP_DAILY_LIMIT", "2"))


def trusted_proxy_hops() -> int:
    return int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))


def samples_file() -> str:
    return os.environ.get("SAMPLES_FILE", "samples/index.json")
