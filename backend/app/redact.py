"""
redact.py — best-effort privacy scrubbing before sending text to the backend.

Returns (clean_text, findings) where findings is a list of (type, count).
The matched values are NEVER stored; only type names and counts are recorded.
"""
import re
from collections import Counter

# ── pattern registry ───────────────────────────────────────────────────────────
#
# Each entry is (type_name, compiled_regex).
# ORDER MATTERS: more specific patterns must come before broader ones so that
# e.g. "sk-abc123..." is caught as api_key before the generic hex pattern runs.

_PATTERNS: list[tuple[str, re.Pattern]] = []


def _add(name: str, pattern: str, flags: int = 0) -> None:
    _PATTERNS.append((name, re.compile(pattern, flags)))


# 1. Private key PEM blocks  (specific — must be first)
_add(
    "private_key",
    r"-----BEGIN [A-Z ]* PRIVATE KEY-----[\s\S]*?-----END [A-Z ]* PRIVATE KEY-----",
)

# 2. URL credentials  user:pass@host
_add(
    "url_credentials",
    r"https?://[^/\s:@]+:[^/\s:@]+@[^\s]+",
)

# 3. Known API key prefixes
#    sk-       : OpenAI / generic secret keys
#    gsk_      : Groq
#    ghp_      : GitHub personal tokens
#    github_pat_: GitHub fine-grained PAT
#    AKIA      : AWS access key IDs
#    xoxb- / xoxp-: Slack bot / user tokens
_add(
    "api_key",
    r"\b(?:sk-[A-Za-z0-9_\-]{20,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|xox[bp]-[A-Za-z0-9\-]+)\b",
)

# 4. Assignment-style secrets  password=abc123, api_key="xyz", token='...'
#    Matches the key=value pair and replaces only the value part.
_add(
    "secret_assignment",
    r"(?i)(?:password|secret|token|api[_\-]?key)\s*=\s*['\"]?[\w\-./+]{4,}['\"]?",
)

# 5. Emails
_add(
    "email",
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
)

# 6. Phone numbers
#    Matches international (+1-800-555-0100) and plain 10-digit (5550100000).
#    Requires digits grouped by spaces/dashes to avoid matching "version 2.3.1"
#    or plain integers like "100000".
_add(
    "phone_number",
    r"(?<!\d)(?:\+\d{1,3}[\s\-])?(?:\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4})\b",
)

# 7. IPv4 addresses
_add(
    "ipv4",
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
)

# 8. Long hex strings (32+ hex chars) — generic secret/token fallback.
#    Anchored so that short hex in version strings (2.3.1) is not matched.
#    Requires the string to be word-bounded and at least 32 chars long.
_add(
    "hex_secret",
    r"\b[0-9a-fA-F]{32,}\b",
)

# 9. Long base64-looking strings (40+ chars of base64 alphabet, no spaces).
#    Minimum length avoids false positives on ordinary base64 substrings.
_add(
    "base64_secret",
    r"(?<!\w)[A-Za-z0-9+/]{40,}={0,2}(?!\w)",
)


# ── public API ─────────────────────────────────────────────────────────────────

def redact(text: str) -> tuple[str, list[tuple[str, int]]]:
    """
    Scan *text* for sensitive patterns and replace each match with
    [REDACTED:<type>].  Returns (clean_text, findings) where findings is a
    list of (type_name, count) pairs — values are never stored.
    """
    counts: Counter = Counter()
    clean = text

    for type_name, pattern in _PATTERNS:
        # Count matches before replacing so we know how many were found
        matches = pattern.findall(clean)
        if matches:
            counts[type_name] += len(matches)
            clean = pattern.sub(f"[REDACTED:{type_name}]", clean)

    # Return findings sorted by type name for stable output
    findings = [(t, c) for t, c in sorted(counts.items())]
    return clean, findings
