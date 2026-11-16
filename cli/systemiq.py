import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import httpx

import hosted_client
from redact import redact

CLI_VERSION = "V1"
PACKAGE_VERSION = "1.0.0"
DEFAULT_DESIGN_OUTPUT = Path("system-design.md")

DEFAULT_API_URL = "https://systemiq-api-pbwg.onrender.com"  # set to the hosted URL at deploy time


def resolve_api_url(cli_value: str | None) -> str:
    """Resolve the backend URL: --api-url flag, then SYSTEMIQ_API_URL, then DEFAULT_API_URL."""
    if cli_value:
        return cli_value.rstrip("/")
    env_value = os.environ.get("SYSTEMIQ_API_URL")
    if env_value:
        return env_value.rstrip("/")
    return DEFAULT_API_URL.rstrip("/")

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


# ── validation rendering ─────────────────────────────────────────────────────

_VAL_COL_ID = 28
_VAL_COL_STATUS = 10
_VAL_COL_PROB = 8


def _format_validation_table(validation: list[dict]) -> list[str]:
    if not validation:
        return []
    lines = ["Validation:"]
    header = f"{'ID':<{_VAL_COL_ID}} {'STATUS':<{_VAL_COL_STATUS}} {'PROB':>{_VAL_COL_PROB}}  SECTIONS"
    lines.append(header)
    lines.append("-" * len(header))
    for v in validation:
        vid = _truncate(str(v.get("id", "")), _VAL_COL_ID)
        status = str(v.get("status", ""))
        prob = v.get("probability")
        prob_display = f"{prob * 100:.0f}%" if isinstance(prob, (int, float)) else "n/a"
        sections = v.get("sections") or []
        sections_display = ", ".join(str(s) for s in sections) if sections else "-"
        lines.append(
            f"{vid:<{_VAL_COL_ID}} {status:<{_VAL_COL_STATUS}} {prob_display:>{_VAL_COL_PROB}}  {sections_display}"
        )
    return lines


def _format_revisions_line(revisions: list[dict]) -> str | None:
    if not revisions:
        return None
    all_numbers = sorted({n for r in revisions for n in (r.get("sections_revised") or [])})
    sections_display = ", ".join(str(n) for n in all_numbers) if all_numbers else "none"
    n_rounds = len(revisions)
    round_word = "round" if n_rounds == 1 else "rounds"
    return f"revised sections: {sections_display} in {n_rounds} {round_word}"


def _format_validation_summary_line(meta: dict) -> str | None:
    """
    Says what really ran: fake/replay decision providers never make a real
    Jev call, so the line must say that instead of claiming real requests.
    """
    status = meta.get("validation_status")
    if status is None:
        return None
    # validation_model is the decision provider's label for the validation
    # call itself; decision_model is fixed to "n/a (validation only)" on
    # /validate, so fall back to it only if validation_model is missing.
    decision_model_label = str(meta.get("validation_model") or meta.get("decision_model") or "").lower()
    if "fake" in decision_model_label:
        return f"validation: {status} (fake), 0 real Jev requests"
    if "replay" in decision_model_label:
        return f"validation: {status} (replayed), 0 real Jev requests"
    calls = meta.get("validation_calls") or 0
    return f"validation: {status}, {calls} Jev requests"


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


# ── design-document file writing ────────────────────────────────────────────────

def _build_design_header(meta: dict) -> str:
    """
    A short Markdown-comment header prepended to the saved design file:
    who/what generated it, the date, which models were used, and a note
    that "provisional" decisions aren't final.
    """
    today = datetime.date.today().isoformat()
    llm_model = meta.get("llm_model") or "unknown"
    decision_model = meta.get("decision_model") or "unknown"
    lines = [
        f"<!-- Generated by System IQ {CLI_VERSION} on {today} -->",
        f"<!-- LLM model: {llm_model} | Decision model: {decision_model} -->",
        "<!-- Decisions marked provisional depend on requirements that were",
        "     not fully specified; confirm them before relying on this design. -->",
    ]
    validation_status = meta.get("validation_status")
    if validation_status == "skipped":
        lines.append("<!-- validation skipped -->")
    elif validation_status is not None:
        lines.append(f"<!-- validated by Jev: {validation_status} -->")
    lines.append("")
    return "\n".join(lines)


def _check_output_path_available(out_path: str | None, force: bool) -> None:
    """
    Refuse early -- before any request is sent -- if the design output file
    already exists and --force is absent. Prevents the hosted flow from
    burning a run's quota only to discover at the end that the file can't
    be written.
    """
    path = Path(out_path) if out_path else DEFAULT_DESIGN_OUTPUT
    if path.exists() and not force:
        print(
            f"error: {path} already exists; use --force to overwrite, or choose --out",
            file=sys.stderr,
        )
        sys.exit(1)


def write_design_file(data: dict, out_path: str | None, force: bool) -> Path:
    """
    Write data["design_markdown"] (plus a short header) to disk.
    Refuses to overwrite an existing file unless force=True.
    """
    path = Path(out_path) if out_path else DEFAULT_DESIGN_OUTPUT

    if path.exists() and not force:
        print(
            f"error: {path} already exists; use --force to overwrite",
            file=sys.stderr,
        )
        sys.exit(1)

    meta = data.get("meta") or {}
    header = _build_design_header(meta)
    markdown = data.get("design_markdown") or ""
    path.write_text(header + "\n" + markdown, encoding="utf-8")
    return path


# ── backend client ─────────────────────────────────────────────────────────────

# The backend may wait up to ~90 s on its own LLM timeout, plus rate-limit
# retry waits, so we give it a generous 150-second window.
REQUEST_TIMEOUT = 150.0

# The design stage runs 4 LLM calls, each possibly waiting out a Groq
# free-tier rate limit, so it needs a much longer window.
DESIGN_STAGE_TIMEOUT = 900.0

# For these statuses, prefer the backend's own "detail" string when the
# body is JSON and has one; otherwise fall back to the fixed message.
# Shared by send_to_backend and send_validate_to_backend.
_FALLBACK_MESSAGES = {
    429: "error: rate limited, wait a minute and try again",
    502: "error: backend could not extract valid requirements",
    503: "error: backend is misconfigured; check server configuration and restart",
    504: "error: backend timed out talking to the model",
}


def _finish_design_output(data: dict, json_mode: bool, out_path: str | None, force: bool) -> None:
    """
    Shared tail for a successful /design (or job) response: billing/fake/
    replay warnings, write the design file, then print either raw JSON or
    the readable rendering. Used by both the local /design flow and the
    hosted job flow so they stay in sync.
    """
    meta = data.get("meta") or {}
    billing = meta.get("decision_billing")
    cost = meta.get("decision_cost")
    if (cost is not None and cost > 0) or (billing is not None and billing != "free"):
        print(
            f"warning: Jev billed as '{billing}' with cost={cost}. "
            "Check OPENCODE_API_KEY usage.",
            file=sys.stderr,
        )

    decision_model_label = str(meta.get("decision_model", "")).lower()
    if "fake" in decision_model_label:
        # Decisions came from the fake (demo) provider, not real Jev output.
        print(
            "WARNING: decisions are FAKE (demo only), not real Jev output",
            file=sys.stderr,
        )
    elif "replay" in decision_model_label:
        # Decisions were replayed from a saved file, not a live Jev call.
        print(
            "WARNING: decisions are REPLAYED from a saved file, not a live Jev call",
            file=sys.stderr,
        )

    # Write the design file to disk regardless of --json: it's a saved
    # artifact, not terminal output, so --json's "raw response only" rule
    # (which is about stdout) doesn't apply to it.
    design_path = None
    if data.get("stage") in ("designed", "validated"):
        design_path = write_design_file(data, out_path, force)

    if json_mode:
        # Raw JSON only — nothing else on stdout.
        print(json.dumps(data, indent=2))
        return

    if design_path is not None:
        print(f"design written to {design_path}")

        group_stats = meta.get("design_group_stats") or []
        if group_stats:
            # Numbers only, straight from design_group_stats -- so retries
            # are visible here without having to read the server log.
            n_groups = len(group_stats)
            total_retries = sum(stat.get("retries", 0) for stat in group_stats)
            total_seconds = round(sum(stat.get("elapsed_seconds", 0) for stat in group_stats), 1)
            total_in = sum(stat.get("prompt_tokens", 0) for stat in group_stats)
            total_out = sum(stat.get("completion_tokens", 0) for stat in group_stats)
            print(
                f"design: {n_groups} groups, {total_retries} retries, "
                f"{total_seconds} s, {total_in}/{total_out} tokens"
            )

        validation = data.get("validation") or []
        if validation:
            print()
            for line in _format_validation_table(validation):
                print(line)

        revisions_line = _format_revisions_line(data.get("revisions") or [])
        if revisions_line:
            print(revisions_line)

        validation_summary_line = _format_validation_summary_line(meta)
        if validation_summary_line:
            print(validation_summary_line)

        warnings = data.get("design_warnings") or []
        if warnings:
            print("design warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        print()

    print_readable_response(data)


def _exit_on_non_200(response: httpx.Response) -> None:
    """Print a message to stderr and exit(1) for any non-200 response."""
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
        print(f"error: HTTP {response.status_code}: {detail}", file=sys.stderr)
        sys.exit(1)


def send_to_backend(
    text: str,
    api_url: str,
    json_mode: bool = False,
    stage: str = "validate",
    out_path: str | None = None,
    force: bool = False,
    max_revisions: int = 1,
    mode: str = "pipeline",
) -> None:
    """
    POST the validated (and possibly redacted) idea text to the backend
    /design endpoint and print the result. By default prints a
    human-readable rendering to stdout; with json_mode=True prints the raw
    response as indented JSON and nothing else on stdout.
    On a "designed"/"validated" response, also writes the design markdown
    to out_path (default ./system-design.md).
    On any error, print a message to stderr and raise SystemExit(1).
    """
    url = f"{api_url.rstrip('/')}/design"
    # "validate" runs the design step too (and more Jev calls on top), so
    # it needs at least as long a window.
    timeout = DESIGN_STAGE_TIMEOUT if stage in ("design", "validate") else REQUEST_TIMEOUT

    if stage in ("design", "validate"):
        # The design step makes several LLM calls in a row, each possibly
        # waiting out a free-tier rate limit -- set expectations up front.
        print("notice: this can take 2 to 5 minutes on the free tier", file=sys.stderr)

    try:
        response = httpx.post(
            url,
            json={"idea": text, "stage": stage, "max_revisions": max_revisions, "mode": mode},
            timeout=timeout,
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

    _exit_on_non_200(response)

    # --- parse and display the successful response ----------------------------

    try:
        data = response.json()
    except Exception:
        # A 200 with a non-JSON body is still an error
        print("error: unexpected response from backend", file=sys.stderr)
        sys.exit(1)

    _finish_design_output(data, json_mode, out_path, force)


# ── validate-only mode (--validate-saved) ───────────────────────────────────────

def _decode_utf8_sig_text(path: Path) -> str:
    """Read a file as text, tolerating a leading UTF-8 BOM."""
    return path.read_bytes().decode("utf-8-sig")


def load_validate_saved(path: str) -> tuple[dict, list, str]:
    """
    Read a saved /design (or /validate) response JSON and pull out the
    three fields /validate needs. Raises ValueError with a clear message
    if the file isn't valid JSON or is missing a needed field.
    """
    try:
        data = json.loads(_decode_utf8_sig_text(Path(path)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}")

    requirements = data.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError(f"{path} is missing 'requirements'")

    design_markdown = data.get("design_markdown")
    if not design_markdown:
        raise ValueError(f"{path} is missing 'design_markdown'")

    decisions = data.get("decisions") or []
    return requirements, decisions, design_markdown


def load_design_file(path: str) -> str:
    """Read a design markdown file, tolerating a leading UTF-8 BOM."""
    try:
        return _decode_utf8_sig_text(Path(path))
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}")


def send_validate_to_backend(
    requirements: dict,
    decisions: list,
    design_markdown: str,
    api_url: str,
    json_mode: bool = False,
    max_revisions: int = 0,
    out_path: str | None = None,
    force: bool = False,
) -> None:
    """
    POST to /validate (not /design): validates an already-produced design,
    optionally revising it. No idea text is involved, so there is no
    redaction step. Writes nothing to disk unless out_path is given.
    """
    url = f"{api_url.rstrip('/')}/validate"
    print(
        "notice: validation only: uses 1 Jev request (no Groq call) unless --revise",
        file=sys.stderr,
    )

    try:
        response = httpx.post(
            url,
            json={
                "requirements": requirements,
                "decisions": decisions,
                "design_markdown": design_markdown,
                "max_revisions": max_revisions,
            },
            timeout=DESIGN_STAGE_TIMEOUT if max_revisions > 0 else REQUEST_TIMEOUT,
        )
    except httpx.ConnectError:
        print("error: backend not running, start it first", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print("error: request timed out", file=sys.stderr)
        sys.exit(1)

    _exit_on_non_200(response)

    try:
        data = response.json()
    except Exception:
        print("error: unexpected response from backend", file=sys.stderr)
        sys.exit(1)

    design_path = None
    if out_path is not None:
        design_path = write_design_file(data, out_path, force)

    if json_mode:
        print(json.dumps(data, indent=2))
        return

    if design_path is not None:
        print(f"design written to {design_path}")

    meta = data.get("meta") or {}
    validation = data.get("validation") or []
    if validation:
        print()
        for line in _format_validation_table(validation):
            print(line)

    revisions_line = _format_revisions_line(data.get("revisions") or [])
    if revisions_line:
        print(revisions_line)

    validation_summary_line = _format_validation_summary_line(meta)
    if validation_summary_line:
        print(validation_summary_line)

    warnings = data.get("design_warnings") or []
    if warnings:
        print("design warnings:")
        for warning in warnings:
            print(f"  - {warning}")


# ── hosted job flow ──────────────────────────────────────────────────────────

_FALLBACK_NOTE_DEFAULT = "generated without Jev decisions (LLM-only mode)"


def _finish_job_result(result: dict, args, job_id: str) -> None:
    """
    Shared with the local flow via _finish_design_output; adds the two
    job-only notices (LLM-only fallback, skipped validation).

    Late safety net: the output file could have appeared while the job was
    running (another process, another run). _check_output_path_available
    already ran before the job was submitted, so re-check here and, if it
    now exists, point at --job so the finished result isn't lost.
    """
    meta = result.get("meta") or {}
    fallback = meta.get("fallback")
    if fallback:
        text = fallback if fallback != _FALLBACK_NOTE_DEFAULT else _FALLBACK_NOTE_DEFAULT
        print(f"Note: {text}.", file=sys.stderr)
    if meta.get("validation_status") == "skipped":
        print("Note: validation was skipped.", file=sys.stderr)

    out_path = Path(args.out) if args.out else DEFAULT_DESIGN_OUTPUT
    if out_path.exists() and not args.force:
        print(
            f"error: {out_path} already exists; use --force to overwrite, or choose --out",
            file=sys.stderr,
        )
        print(f"resume with --job {job_id} --out <other path>", file=sys.stderr)
        sys.exit(1)

    _finish_design_output(result, args.json, args.out, args.force)


def _run_hosted_flow(clean_text: str, access_code: str | None, args, mode_info: dict) -> None:
    access_code = hosted_client.require_access_code(access_code)

    max_chars = mode_info.get("max_idea_chars") or 2000
    hosted_client.check_idea_length(clean_text, max_chars)

    hosted_client.confirm_hosted_run(args.yes)

    job_info = hosted_client.submit_job(args.api_url, access_code, clean_text)
    job_id = job_info["job_id"]
    print(f"Job: {job_id} (resume with --job {job_id} within 60 minutes)")

    result = hosted_client.poll_job(args.api_url, job_id)
    _finish_job_result(result, args, job_id)


# ── first-run welcome ────────────────────────────────────────────────────────

WELCOME = r"""            
/\     /\
  \ _____\
   (_)-(_)
   Welcome to SystemIQ !!!"""

_WELCOME_MARKER_NAME = "welcome_shown"


def config_dir() -> Path:
    """SYSTEMIQ_CONFIG_DIR if set; else %APPDATA%\\systemiq on Windows, else
    $XDG_CONFIG_HOME/systemiq or ~/.config/systemiq."""
    override = os.environ.get("SYSTEMIQ_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "systemiq"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "systemiq"
    return Path.home() / ".config" / "systemiq"


def maybe_show_welcome(args) -> None:
    """
    Print WELCOME to stderr once, on the first run only. --version and
    --help never reach here -- argparse exits during parse_args() for both
    -- so they need no explicit check here.
    """
    if not sys.stderr.isatty():
        return
    if args.json or args.quiet:
        return
    if os.environ.get("SYSTEMIQ_NO_WELCOME"):
        return

    marker = config_dir() / _WELCOME_MARKER_NAME
    if marker.exists():
        return

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("shown")
    except OSError:
        # Can't write the marker (e.g. the config path isn't a writable
        # directory) -- never crash the CLI over a cosmetic welcome message.
        return

    print(WELCOME, file=sys.stderr)


NO_ARGS_MESSAGE = """System IQ: turn a project idea into a structured system design.

Quick start:
  systemiq --access-code <your code> "A web app for a small clinic where patients book appointments online"
  systemiq --sample 1        download a ready-made sample design (no code needed)
  systemiq --help            all options

The hosted demo takes about 3 minutes per design and daily capacity is limited. See the README."""


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SystemIQ CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment: SYSTEMIQ_API_URL (default backend URL), "
            "SYSTEMIQ_ACCESS_CODE (hosted demo access code), "
            "SYSTEMIQ_CONFIG_DIR (where the welcome marker is stored), "
            "SYSTEMIQ_NO_WELCOME (set to disable the first-run welcome message).\n"
            "Exit codes: 0 success, 1 error, 2 no arguments given, "
            "3 no design generated (sample or capacity)."
        ),
    )
    common = parser.add_argument_group("Common options")
    advanced = parser.add_argument_group("Advanced and development options")

    common.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Input to process (not required with --validate-saved)",
    )
    common.add_argument(
        "--access-code",
        default=None,
        help="Access code for the hosted demo (default: $SYSTEMIQ_ACCESS_CODE)",
    )
    common.add_argument(
        "--yes",
        action="store_true",
        help="Skip the hosted-demo confirmation prompt",
    )
    common.add_argument(
        "--out",
        default=None,
        help="Where to write the design markdown (default: ./system-design.md)",
    )
    common.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing design output file",
    )
    common.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Download published sample design N (1-3); needs no server and no access code",
    )
    common.add_argument(
        "--job",
        default=None,
        metavar="ID",
        help="Resume polling a hosted job by id instead of submitting a new idea",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and show what would be sent, without calling the backend",
    )
    common.add_argument(
        "--version",
        action="version",
        version=f"systemiq {PACKAGE_VERSION}",
    )

    advanced.add_argument(
        "--api-url",
        default=None,
        help="Base URL of the SystemIQ backend (default: $SYSTEMIQ_API_URL or "
             f"{DEFAULT_API_URL})",
    )
    advanced.add_argument(
        "--stage",
        choices=["extract", "decide", "design", "validate"],
        default="validate",
        help="Pipeline stage to stop at (default: validate)",
    )
    advanced.add_argument(
        "--mode",
        choices=["pipeline", "llm_only"],
        default="pipeline",
        help="pipeline (default): extract+decide+design+validate. "
             "llm_only: design with no Jev decisions at all (baseline)",
    )
    advanced.add_argument(
        "--no-validate",
        action="store_true",
        help="Stop at the design stage; skip Jev validation",
    )
    advanced.add_argument(
        "--max-revisions",
        type=int,
        default=1,
        help="How many revise-then-revalidate rounds the validate stage may use (default: 1)",
    )
    advanced.add_argument(
        "--validate-saved",
        default=None,
        metavar="PATH",
        help="Validate a saved /design response JSON instead of sending a new idea",
    )
    advanced.add_argument(
        "--design-file",
        default=None,
        metavar="PATH",
        help="With --validate-saved: read the design markdown from this .md file instead",
    )
    advanced.add_argument(
        "--revise",
        action="store_true",
        help="With --validate-saved: send max_revisions from --max-revisions instead of 0",
    )
    advanced.add_argument(
        "--json",
        action="store_true",
        help="Print the raw backend response as JSON instead of a readable summary",
    )
    advanced.add_argument(
        "--no-redact",
        action="store_true",
        help="Skip redaction and send the original text (prints a warning)",
    )
    advanced.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the first-run welcome message",
    )
    advanced.add_argument(
        "--welcome",
        action="store_true",
        help="Show the welcome message and exit",
    )

    args = parser.parse_args()

    # --- --welcome: always prints and exits, regardless of the marker ---------

    if args.welcome:
        print(WELCOME)
        return

    args.api_url = resolve_api_url(args.api_url)
    effective_stage = "design" if args.no_validate else args.stage

    maybe_show_welcome(args)

    # --- --sample: download a published sample, no server contact -------------

    if args.sample is not None:
        hosted_client.fetch_sample(args.sample, args.out, args.force)
        return

    # --- --validate-saved: a completely separate, idea-free path ---------------

    if args.validate_saved:
        try:
            requirements, decisions, design_markdown = load_validate_saved(args.validate_saved)
            if args.design_file:
                design_markdown = load_design_file(args.design_file)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)

        send_validate_to_backend(
            requirements,
            decisions,
            design_markdown,
            args.api_url,
            json_mode=args.json,
            max_revisions=args.max_revisions if args.revise else 0,
            out_path=args.out,
            force=args.force,
        )
        return

    # --- --job: resume polling an existing hosted job, nothing else ------------

    if args.job:
        _check_output_path_available(args.out, args.force)
        mode_info = hosted_client.detect_mode(args.api_url)
        if not mode_info.get("hosted"):
            print("--job needs a hosted server.", file=sys.stderr)
            sys.exit(1)
        result = hosted_client.poll_job(args.api_url, args.job)
        _finish_job_result(result, args, args.job)
        return

    if not args.input:
        print(NO_ARGS_MESSAGE)
        sys.exit(2)

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

    access_code = hosted_client.resolve_access_code(args.access_code)

    # --- dry-run branch -------------------------------------------------------
    # Never contacts the server (not even healthz).

    if args.dry_run:
        if access_code:
            print(f"dry-run: would POST to {args.api_url}/jobs")
            print(f"dry-run: {len(clean_text)} characters of validated input")
            print(f"dry-run: preview: {clean_text[:200]}")
            hosted_client.print_privacy_notice()
            return

        url = f"{args.api_url.rstrip('/')}/design"
        print(f"dry-run: would POST to {url}")
        print(f"dry-run: {len(clean_text)} characters of validated input")
        # Show first 200 chars of the redacted text so the user can verify
        print(f"dry-run: preview: {clean_text[:200]}")
        return

    # --- refuse early if the output file already exists -----------------------
    # Before any request (healthz included): losing a hosted run's quota to a
    # file-exists error discovered only after the design is finished is the
    # bug this guards against. Applies to both the hosted and local flows below.

    _check_output_path_available(args.out, args.force)

    # --- mode detection: decide hosted vs. the existing local flow -------------

    mode_info = hosted_client.detect_mode(args.api_url)

    if mode_info.get("hosted"):
        _run_hosted_flow(clean_text, access_code, args, mode_info)
        return

    # --- existing local flow, unchanged -----------------------------------------

    print(
        f"sending your text to {args.api_url} (forwarded to the AI provider)",
        file=sys.stderr,
    )

    send_to_backend(
        clean_text,
        args.api_url,
        json_mode=args.json,
        stage=effective_stage,
        out_path=args.out,
        force=args.force,
        max_revisions=args.max_revisions,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()
