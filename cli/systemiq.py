import argparse
import json
import sys
from pathlib import Path

import httpx

from redact import redact

MAX_BYTES = 20 * 1024  # 20 KB limit for both file and inline input


def reject_if_blank(text: str) -> None:
    # An empty submission is never useful to process
    if not text.strip():
        raise ValueError("input is empty or whitespace-only")


def classify_input(raw: str) -> str:
    """Return 'file' or 'inline'. Raises ValueError for directory / missing file-like paths."""
    path = Path(raw)

    if path.is_dir():
        # Directories are not readable ideas or text files
        raise ValueError(f"path is a directory: {raw}")

    if path.is_file():
        return "file"

    # Looks like a file name the user mistyped — flag it rather than treating as inline
    if path.suffix.lower() in {".md", ".txt"}:
        raise ValueError(f"file not found: {raw}")

    return "inline"


def validate_file(path: Path) -> str:
    """Read and validate a file; return its text content."""
    # Only plain-text formats are supported
    if path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("file type not allowed; use .md or .txt")

    # Check size before reading to avoid loading huge files into memory
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"file exceeds 20 KB limit ({size} bytes)")

    raw_bytes = path.read_bytes()

    # Binary files will not decode cleanly
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("file is not valid UTF-8 text")

    # A file full of blank lines is the same as no input
    if not text.strip():
        raise ValueError("file content is empty or whitespace-only")

    return text


def validate_inline(raw: str) -> str:
    """Validate inline idea text; return it unchanged."""
    # Respect the same size ceiling as files for consistency
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("inline input exceeds 20 KB limit")
    return raw


def reject_null_bytes(text: str) -> None:
    # Null bytes indicate binary data or a malformed string
    if "\x00" in text:
        raise ValueError("input contains null bytes")


def load_input(raw: str) -> str:
    """Return validated text from raw CLI input, or raise ValueError."""
    reject_if_blank(raw)

    mode = classify_input(raw)

    if mode == "file":
        text = validate_file(Path(raw))
    else:
        text = validate_inline(raw)

    reject_null_bytes(text)
    return text


# ── redaction summary ──────────────────────────────────────────────────────────

def print_redaction_summary(findings: list[tuple[str, int]]) -> None:
    """Print a one-line redaction summary to stderr. Prints nothing if clean."""
    if not findings:
        return
    total = sum(c for _, c in findings)
    parts = ", ".join(f"{t} x{c}" for t, c in findings)
    print(f"redacted {total} item(s): {parts}", file=sys.stderr)


# ── human-readable response rendering ───────────────────────────────────────────
# Output here must be ASCII-only (some Windows consoles choke on non-ASCII).

# The tri-state boolean fields, in display order (matches backend/app/schemas.py).
_FLAG_FIELDS = (
    "realtime",
    "geospatial",
    "authentication",
    "search_filtering",
    "media_storage",
    "payments",
    "offline_support",
)

# Decisions table column widths; sized to land close to ~100 columns wide.
_COL_ID = 34
_COL_CHOICE = 28
_COL_PROB = 8
_COL_STATUS = 20
_COL_FLAG = 3


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, adding "..." when it was cut (ASCII only)."""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _format_requirements_block(req: dict) -> list[str]:
    """
    Render the "Requirements:" section. Tolerates a response missing
    optional fields (evidence, or the requirements object being partial).
    """
    lines = ["Requirements:"]

    app_type = req.get("app_type")
    lines.append(f"  app type: {app_type if app_type else 'not specified'}")

    summary = req.get("project_summary")
    if summary:
        lines.append(f"  summary: {summary}")

    core_features = req.get("core_features") or []
    if core_features:
        lines.append("  core features:")
        for feature in core_features:
            lines.append(f"    - {feature}")

    evidence = req.get("evidence") or {}
    for field in _FLAG_FIELDS:
        value = req.get(field)
        if value is None:
            continue  # tri-state: only show fields the model actually addressed
        word = "yes" if value else "no"
        quote = evidence.get(field)
        if quote:
            lines.append(f'  {field}: {word} (evidence: "{quote}")')
        else:
            lines.append(f"  {field}: {word}")

    unknowns = req.get("unknowns") or []
    if unknowns:
        lines.append("  unknowns:")
        for item in unknowns:
            lines.append(f"    - {item}")

    return lines


def _format_decisions_table(decisions: list[dict]) -> list[str]:
    """
    Render the "Decisions:" table plus the question-text list under it.
    Tolerates decisions missing "question" (older responses).
    """
    if not decisions:
        return []

    lines = ["Decisions:"]
    header = (
        f"{'ID':<{_COL_ID}} {'CHOICE':<{_COL_CHOICE}} "
        f"{'PROB':>{_COL_PROB}} {'STATUS':<{_COL_STATUS}} {'?':<{_COL_FLAG}}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for d in decisions:
        qid = _truncate(str(d.get("id", "")), _COL_ID)
        status = str(d.get("status", ""))
        choice = d.get("choice")
        # For yes/no (noul) questions, choice is None; show the status
        # (yes/no/uncertain) in its place instead.
        choice_display = _truncate(str(choice if choice else status), _COL_CHOICE)
        prob = d.get("probability")
        prob_display = f"{prob * 100:.0f}%" if isinstance(prob, (int, float)) else "n/a"
        marker = "?" if d.get("based_on_unknowns") else ""
        lines.append(
            f"{qid:<{_COL_ID}} {choice_display:<{_COL_CHOICE}} "
            f"{prob_display:>{_COL_PROB}} {status:<{_COL_STATUS}} {marker:<{_COL_FLAG}}"
        )

    lines.append("")
    lines.append("Questions:")
    for i, d in enumerate(decisions, start=1):
        qid = d.get("id", "")
        question = d.get("question")  # absent on older responses
        text = f"{i}. {qid}: {question}" if question else f"{i}. {qid}"
        lines.append("  " + _truncate(text, 96))

    return lines


def _format_summary_line(meta: dict) -> str | None:
    """Render the final "decision model / token counts" line, or None if no meta."""
    if not meta:
        return None
    model = meta.get("decision_model", "unknown")
    in_tok = meta.get("input_tokens")
    out_tok = meta.get("output_tokens")
    in_display = in_tok if in_tok is not None else "n/a"
    out_display = out_tok if out_tok is not None else "n/a"
    return f"model: {model} | tokens: {in_display} in / {out_display} out"


def print_readable_response(data: dict) -> None:
    """Print the backend's /design response as human-readable ASCII text."""
    meta = data.get("meta") or {}

    for line in _format_requirements_block(data.get("requirements") or {}):
        print(line)

    decision_lines = _format_decisions_table(data.get("decisions") or [])
    if decision_lines:
        print()
        for line in decision_lines:
            print(line)

    summary_line = _format_summary_line(meta)
    if summary_line:
        print()
        print(summary_line)


# ── backend client ─────────────────────────────────────────────────────────────

# The backend may wait up to ~90 s on its own LLM timeout, plus rate-limit
# retry waits, so we give it a generous 150-second window.
REQUEST_TIMEOUT = 150.0


def send_to_backend(text: str, api_url: str, json_mode: bool = False) -> None:
    """
    POST the validated (and possibly redacted) idea text to the backend
    /design endpoint and print the result. By default prints a
    human-readable rendering to stdout; with json_mode=True prints the raw
    response as indented JSON and nothing else on stdout.
    On any error, print a message to stderr and raise SystemExit(1).
    """
    url = f"{api_url.rstrip('/')}/design"

    try:
        response = httpx.post(
            url,
            json={"idea": text},
            timeout=REQUEST_TIMEOUT,
        )

    except httpx.ConnectError:
        # The server is not listening — most likely the backend is not running
        print("error: backend not running, start it first", file=sys.stderr)
        sys.exit(1)

    except httpx.TimeoutException:
        # The request took longer than REQUEST_TIMEOUT seconds
        print("error: request timed out", file=sys.stderr)
        sys.exit(1)

    # --- handle non-200 status codes -----------------------------------------

    # For these statuses, prefer the backend's own "detail" string when the
    # body is JSON and has one; otherwise fall back to the fixed message.
    _FALLBACK_MESSAGES = {
        429: "error: rate limited, wait a minute and try again",
        502: "error: backend could not extract valid requirements",
        503: "error: backend is misconfigured; check server configuration and restart",
        504: "error: backend timed out talking to the model",
    }

    if response.status_code in _FALLBACK_MESSAGES:
        detail = None
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("detail"), str) and body["detail"]:
                detail = body["detail"]
        except Exception:
            detail = None

        if detail:
            print(f"error: {detail}", file=sys.stderr)
        else:
            print(_FALLBACK_MESSAGES[response.status_code], file=sys.stderr)
        sys.exit(1)

    if response.status_code != 200:
        # Attempt to pull a human-readable message from the JSON body
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print(
            f"error: HTTP {response.status_code}: {detail}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- parse and display the successful response ----------------------------

    try:
        data = response.json()
    except Exception:
        # A 200 with a non-JSON body is still an error
        print("error: unexpected response from backend", file=sys.stderr)
        sys.exit(1)

    # Warn if the decision provider charged real money or billed as non-free.
    meta = data.get("meta") or {}
    billing = meta.get("decision_billing")
    cost = meta.get("decision_cost")
    if (cost is not None and cost > 0) or (billing is not None and billing != "free"):
        print(
            f"warning: Jev billed as '{billing}' with cost={cost}. "
            "Check OPENCODE_API_KEY usage.",
            file=sys.stderr,
        )

    # Decisions came from the fake (demo) provider, not real Jev output.
    if "fake" in str(meta.get("decision_model", "")).lower():
        print(
            "WARNING: decisions are FAKE (demo only), not real Jev output",
            file=sys.stderr,
        )

    if json_mode:
        # Raw JSON only — nothing else on stdout.
        print(json.dumps(data, indent=2))
        return

    print_readable_response(data)


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SystemIQ CLI")
    parser.add_argument("input", help="Input to process")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the SystemIQ backend (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and show what would be sent, without calling the backend",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Skip redaction and send the original text (prints a warning)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw backend response as JSON instead of a readable summary",
    )
    args = parser.parse_args()

    try:
        text = load_input(args.input)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- redaction step -------------------------------------------------------

    if args.no_redact:
        # Warn the user that their text will be sent as-is
        print(
            "warning: --no-redact is set; your text will be sent without scrubbing",
            file=sys.stderr,
        )
        clean_text = text
        findings: list[tuple[str, int]] = []
    else:
        clean_text, findings = redact(text)
        print_redaction_summary(findings)

    # --- dry-run branch -------------------------------------------------------

    if args.dry_run:
        url = f"{args.api_url.rstrip('/')}/design"
        print(f"dry-run: would POST to {url}")
        print(f"dry-run: {len(clean_text)} characters of validated input")
        # Show first 200 chars of the redacted text so the user can verify
        print(f"dry-run: preview: {clean_text[:200]}")
        return

    # --- always print a one-line notice before making any network call --------
    print(
        f"sending your text to {args.api_url} (forwarded to the AI provider)",
        file=sys.stderr,
    )

    send_to_backend(clean_text, args.api_url, json_mode=args.json)


if __name__ == "__main__":
    main()
