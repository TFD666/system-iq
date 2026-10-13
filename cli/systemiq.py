import argparse
import sys
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description="SystemIQ CLI")
    parser.add_argument("input", help="Input to process")
    args = parser.parse_args()

    try:
        text = load_input(args.input)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    mode = "file" if Path(args.input).is_file() else "inline"
    print(f"OK: {mode} input, {len(text)} characters")
    print(text[:200])


if __name__ == "__main__":
    main()
