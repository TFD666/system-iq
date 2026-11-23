"""Client helpers for the hosted System IQ demo (job mode)."""

import os
import re
import sys
import time
from pathlib import Path

import httpx

WAKE_TIMEOUT_SECONDS = 240
WAKE_POLL_SECONDS = 5
JOB_POLL_SECONDS = 5
JOB_TIMEOUT_SECONDS = 1200
SAMPLES_PAGE_URL = "https://github.com/TFD666/system-iq/tree/main/samples"
SAMPLES_INDEX_URL = "https://raw.githubusercontent.com/TFD666/system-iq/main/samples/index.json"
# change to the zero-retention wording only after it is verified
GROQ_RETENTION_LINE = "Groq: zero data retention is enabled in the account settings for this demo."

HEALTHZ_TIMEOUT = 5.0
REQUEST_TIMEOUT = 10.0

PRIVACY_NOTICE_LINES = (
    "Before you send:",
    "- Your idea is sent to Groq and OpenCode (both US) to generate the design.",
    f"- {GROQ_RETENTION_LINE}",
    "- OpenCode free tier: may use submitted text to improve their service.",
    "- System IQ redacts obvious secrets, keeps your design in memory up to 60 minutes so you can download it,",
    "  then deletes it. Nothing is written to disk. Only counts are logged.",
    "- Do not enter secrets, personal data, or confidential company info.",
)


def print_privacy_notice() -> None:
    for line in PRIVACY_NOTICE_LINES:
        print(line, file=sys.stderr)


# ── access code ─────────────────────────────────────────────────────────────

def resolve_access_code(cli_value: str | None) -> str | None:
    """--access-code flag, then SYSTEMIQ_ACCESS_CODE. Never printed or logged."""
    if cli_value:
        return cli_value
    return os.environ.get("SYSTEMIQ_ACCESS_CODE") or None


def require_access_code(cli_value: str | None) -> str:
    code = resolve_access_code(cli_value)
    if not code:
        print("An access code is required for the hosted demo. See the README.", file=sys.stderr)
        sys.exit(1)
    return code


# ── mode detection and wake-up ────────────────────────────────────────────────

def is_localhost(url: str) -> bool:
    host = httpx.URL(url).host
    return host in ("localhost", "127.0.0.1")


def get_healthz(url: str, timeout: float = HEALTHZ_TIMEOUT) -> dict | None:
    """One healthz attempt. None on any connection problem, bad status or bad body."""
    try:
        response = httpx.get(f"{url}/healthz", timeout=timeout)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except Exception:
        return None


def detect_mode(url: str, sleep=time.sleep) -> dict:
    """
    GET /healthz. Returns its body on success.
    Not reachable and localhost -> today's "backend not running" message, exit 1.
    Not reachable and not localhost -> wake-up retry loop, then exit 1 if still down.
    """
    data = get_healthz(url)
    if data is not None:
        return data

    if is_localhost(url):
        print("error: backend not running, start it first", file=sys.stderr)
        sys.exit(1)

    print("Server waking up, this can take a minute or two...", file=sys.stderr)
    waited = 0
    while waited < WAKE_TIMEOUT_SECONDS:
        sleep(WAKE_POLL_SECONDS)
        waited += WAKE_POLL_SECONDS
        data = get_healthz(url)
        if data is not None:
            return data

    print(
        f"Server unavailable, try again later or see sample designs: {SAMPLES_PAGE_URL}",
        file=sys.stderr,
    )
    sys.exit(1)


# ── pre-flight checks ─────────────────────────────────────────────────────────

def check_idea_length(text: str, max_idea_chars: int) -> None:
    if len(text) > max_idea_chars:
        print(
            f"Idea is too long for the hosted demo (max {max_idea_chars} characters).",
            file=sys.stderr,
        )
        sys.exit(1)


def confirm_hosted_run(yes: bool, isatty: bool | None = None, input_func=None) -> None:
    """Print the privacy notice (always), then confirm unless --yes."""
    print_privacy_notice()
    if yes:
        return
    if isatty is None:
        isatty = sys.stdin.isatty()
    if not isatty:
        print("Add --yes to confirm in a non-interactive shell.", file=sys.stderr)
        sys.exit(1)
    if input_func is None:
        input_func = input  # looked up at call time so tests can patch builtins.input
    answer = input_func("Continue? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        sys.exit(1)


# ── job submission ────────────────────────────────────────────────────────────

_JOB_FALLBACK_MESSAGES = {
    403: "error: invalid access code",
    422: "error: idea is invalid",
    429: "error: daily limit reached, try again tomorrow",
    503: "error: server is busy, try again later",
}


def print_sample_response(body: dict) -> None:
    reason = body.get("reason")
    if reason:
        print(f"reason: {reason}")
    for sample in body.get("samples") or []:
        print(f"- {sample.get('title')}: {sample.get('url')}")
    print("No design was generated.")


def _exit_on_job_error(response: httpx.Response) -> None:
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
        print(
            _JOB_FALLBACK_MESSAGES.get(response.status_code, f"error: HTTP {response.status_code}"),
            file=sys.stderr,
        )
    sys.exit(1)


def submit_job(url: str, access_code: str, idea: str) -> dict:
    """POST /jobs. Returns {"job_id", "status", "position"} on 202. Exits 3 on a
    sample response, exits 1 on any error. Never logs the access code."""
    try:
        response = httpx.post(
            f"{url}/jobs",
            json={"idea": idea},
            headers={"X-Access-Code": access_code},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.HTTPError:
        print("error: could not reach the server", file=sys.stderr)
        sys.exit(1)

    if response.status_code == 202:
        return response.json()

    if response.status_code == 200:
        try:
            body = response.json()
        except Exception:
            body = {}
        if body.get("sample") or body.get("status") == "sample":
            print_sample_response(body)
            sys.exit(3)

    _exit_on_job_error(response)


# ── job polling ────────────────────────────────────────────────────────────────

def _format_job_line(status: str, stage: str | None, detail: dict | None, position: int | None) -> str:
    if status == "queued":
        return f"Queued (position {position})" if position is not None else "Queued"
    if status == "done":
        return "Done"
    if stage == "extracting":
        return "Extracting requirements"
    if stage == "deciding":
        return "Jev deciding"
    if stage == "writing":
        d = detail or {}
        return f"Writing design ({d.get('group')}/{d.get('of')})"
    if stage == "validating":
        return "Validating"
    return status or ""


def poll_job(url: str, job_id: str, clock=time.time, sleep=time.sleep) -> dict:
    """GET /jobs/{id} every JOB_POLL_SECONDS until done/failed/expired/timeout."""
    start = clock()
    last_state = None
    consecutive_errors = 0

    while True:
        if clock() - start > JOB_TIMEOUT_SECONDS:
            minutes = JOB_TIMEOUT_SECONDS // 60
            print(
                f"Still running after {minutes} minutes. You can collect it later with --job {job_id}.",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            response = httpx.get(f"{url}/jobs/{job_id}", timeout=REQUEST_TIMEOUT)
        except httpx.HTTPError:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                print("error: lost contact with the server while waiting for the job", file=sys.stderr)
                sys.exit(1)
            sleep(JOB_POLL_SECONDS)
            continue

        if response.status_code == 404:
            print("Server restarted or the job expired. Please run again.", file=sys.stderr)
            sys.exit(1)

        try:
            body = response.json()
        except Exception:
            body = None

        if response.status_code != 200 or body is None:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                print("error: lost contact with the server while waiting for the job", file=sys.stderr)
                sys.exit(1)
            sleep(JOB_POLL_SECONDS)
            continue

        consecutive_errors = 0
        status = body.get("status")
        stage = body.get("stage")
        detail = body.get("detail")
        position = body.get("position")

        state = (status, stage, detail, position)
        if state != last_state:
            print(_format_job_line(status, stage, detail, position))
            last_state = state

        if status == "done":
            return body.get("result")
        if status == "failed":
            err = body.get("error") or {}
            print(err.get("message", "job failed"), file=sys.stderr)
            sys.exit(1)

        sleep(JOB_POLL_SECONDS)


# ── samples (no server needed) ───────────────────────────────────────────────

_BLOB_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)/blob/")


def blob_url_to_raw(url: str) -> str:
    # Defensive: heal a URL built from a raw Windows path (backslashes) before
    # matching the blob pattern, which expects forward slashes.
    url = url.replace("\\", "/")
    return _BLOB_PATTERN.sub(r"raw.githubusercontent.com/\1/\2/", url)


def fetch_sample(
    n: int, path: Path, *, force: bool = False, auto: bool = False,
) -> None:
    try:
        response = httpx.get(SAMPLES_INDEX_URL, timeout=REQUEST_TIMEOUT)
        entries = response.json()
    except Exception:
        entries = []

    if not isinstance(entries, list) or n < 1 or n > len(entries):
        print(f"No sample {n} is published yet.", file=sys.stderr)
        sys.exit(1)

    raw_url = blob_url_to_raw(entries[n - 1]["url"])
    try:
        markdown = httpx.get(raw_url, timeout=REQUEST_TIMEOUT).text
    except Exception:
        print(f"No sample {n} is published yet.", file=sys.stderr)
        sys.exit(1)

    if force:
        path.write_text(markdown, encoding="utf-8")
    elif auto:
        while True:
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(markdown)
                break
            except FileExistsError:
                from systemiq import next_free_path
                path = next_free_path(Path("system-design.SAMPLE.md"))
    else:
        if path.exists():
            print(f"error: {path} already exists; use --force to overwrite", file=sys.stderr)
            sys.exit(1)
        path.write_text(markdown, encoding="utf-8")

    print(f"sample written to {os.path.abspath(path)}")
