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


# ── backend client ─────────────────────────────────────────────────────────────

# The backend may wait up to ~90 s on its own LLM timeout, plus rate-limit
# retry waits, so we give it a generous 150-second window.
REQUEST_TIMEOUT = 150.0


def send_to_backend(text: str, api_url: str) -> None:
    """
    POST the validated (and possibly redacted) idea text to the backend
    /design endpoint and print the returned requirements as indented JSON.
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

    if response.status_code == 429:
        print("error: rate limited, wait a minute and try again", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 502:
        print("error: backend could not extract valid requirements", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 504:
        print("error: backend timed out talking to the model", file=sys.stderr)
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

    # Print the requirements object as human-readable indented JSON
    print(json.dumps(data, indent=2))


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

    send_to_backend(clean_text, args.api_url)


if __name__ == "__main__":
    main()
