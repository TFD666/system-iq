"""
Send every (idea, version, repeat) combination to a running backend's
POST /design and save the raw response to eval/m6/runs/<id>.json plus a
small <id>.meta.json (idea, version, repeat, start/end time, seconds).

Version A = mode llm_only, stage "design" (no Jev call at all).
Version B = mode pipeline, stage "validate", max_revisions 0.

Real network calls on purpose (this is the eval harness, not a test) --
--max-runs and --sleep exist specifically to keep that bounded and polite.

Stops immediately, without saving, on any sign a response isn't real:
non-200 (prints status + detail, never retries), or a response that fails
the real-run checks (A: needs llm_model + design_group_stats; B: needs a
real decision_model/validation_model, real validation_input_tokens, and
validation_status != "skipped"). Prints only file names, statuses,
counts and seconds -- never idea or design text.
"""

import argparse
import json
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
DEFAULT_IDEAS_DIR = HERE.parent / "ideas"
RUNS_DIR = HERE / "runs"

REQUEST_TIMEOUT = 900.0


def _read_text_bom(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def _build_request_body(idea_text: str, version: str) -> dict:
    if version == "A":
        return {"idea": idea_text, "stage": "design", "mode": "llm_only", "max_revisions": 0}
    return {"idea": idea_text, "stage": "validate", "mode": "pipeline", "max_revisions": 0}


def _check_real_run(version: str, meta: dict) -> str | None:
    """Returns None if `meta` looks like a real run, else a reason string."""
    if version == "A":
        if not meta.get("llm_model"):
            return "llm_model missing"
        if not meta.get("design_group_stats"):
            return "design_group_stats missing"
        return None

    decision_model = str(meta.get("decision_model") or "")
    if "fake" in decision_model.lower() or "replay" in decision_model.lower():
        return f"decision_model is {decision_model!r}"
    validation_model = meta.get("validation_model")
    if not validation_model:
        return "validation_model missing"
    if "fake" in str(validation_model).lower() or "replay" in str(validation_model).lower():
        return f"validation_model is {validation_model!r}"
    if not meta.get("validation_input_tokens"):
        return "validation_input_tokens is 0 or missing"
    if meta.get("validation_status") == "skipped":
        return "validation_status is skipped"
    return None


def _build_jobs(ideas_dir: Path, versions: list[str], repeats: int) -> list[dict]:
    idea_paths = sorted(ideas_dir.glob("*.md"), key=lambda p: p.stem)
    jobs = []
    for idea_path in idea_paths:
        for version in versions:
            for repeat in range(1, repeats + 1):
                jobs.append({"idea": idea_path.stem, "idea_path": idea_path, "version": version, "repeat": repeat})
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the M6 eval (version A vs B) against /design.")
    parser.add_argument("--ideas-dir", default=str(DEFAULT_IDEAS_DIR), metavar="PATH")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--max-runs", type=int, default=4, help="Max real requests this run.")
    parser.add_argument("--only-idea", default=None, help="Comma-separated idea file stems to run.")
    parser.add_argument("--only-version", choices=["A", "B"], default=None)
    parser.add_argument("--repeats", type=int, default=1, help="Repeats per (idea, version).")
    parser.add_argument("--sleep", type=float, default=10.0, help="Seconds between requests.")
    parser.add_argument("--force", action="store_true", help="Re-run jobs that already have a result.")
    args = parser.parse_args()

    ideas_dir = Path(args.ideas_dir)
    versions = [args.only_version] if args.only_version else ["A", "B"]
    jobs = _build_jobs(ideas_dir, versions, args.repeats)
    if args.only_idea:
        wanted = set(args.only_idea.split(","))
        jobs = [j for j in jobs if j["idea"] in wanted]

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    requests_used = 0
    stopped_reason = None
    pending_candidates: list[str] = []

    for index, job in enumerate(jobs):
        run_id = f"{job['idea']}__{job['version']}__r{job['repeat']}"
        result_path = RUNS_DIR / f"{run_id}.json"
        meta_path = RUNS_DIR / f"{run_id}.meta.json"

        if result_path.exists() and not args.force:
            print(f"skip (already has a result): {run_id}")
            continue

        if requests_used >= args.max_runs:
            print(f"stop: max runs ({args.max_runs}) reached")
            pending_candidates.extend(f"{j['idea']}__{j['version']}__r{j['repeat']}" for j in jobs[index:])
            stopped_reason = f"max runs ({args.max_runs}) reached"
            break

        idea_text = _read_text_bom(job["idea_path"])
        body = _build_request_body(idea_text, job["version"])

        if requests_used > 0:
            time.sleep(args.sleep)

        start_time = time.time()
        try:
            response = httpx.post(
                f"{args.api_url.rstrip('/')}/design", json=body, timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            print(f"stop: {run_id}: request failed ({type(exc).__name__})")
            pending_candidates.extend(f"{j['idea']}__{j['version']}__r{j['repeat']}" for j in jobs[index:])
            stopped_reason = f"request failed for {run_id}"
            break
        end_time = time.time()

        requests_used += 1

        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = None
            print(f"stop: {run_id}: HTTP {response.status_code}: {detail}")
            pending_candidates.extend(f"{j['idea']}__{j['version']}__r{j['repeat']}" for j in jobs[index:])
            stopped_reason = f"HTTP {response.status_code} on {run_id}"
            break

        response_body = response.json()
        meta = response_body.get("meta") or {}
        reason = _check_real_run(job["version"], meta)
        if reason is not None:
            print(f"stop: {run_id}: not a real run ({reason}); not saving")
            pending_candidates.extend(f"{j['idea']}__{j['version']}__r{j['repeat']}" for j in jobs[index:])
            stopped_reason = f"{reason} on {run_id}"
            break

        seconds = end_time - start_time
        result_path.write_text(json.dumps(response_body, indent=2), encoding="utf-8")
        meta_path.write_text(
            json.dumps({
                "idea": job["idea"],
                "version": job["version"],
                "repeat": job["repeat"],
                "start_time": start_time,
                "end_time": end_time,
                "seconds": seconds,
            }, indent=2),
            encoding="utf-8",
        )
        print(f"saved: {run_id}: status={response_body.get('stage')} seconds={seconds:.1f}")

    pending = [run_id for run_id in pending_candidates if not (RUNS_DIR / f"{run_id}.json").exists()]

    print(f"requests used: {requests_used}")
    print("pending: " + (", ".join(pending) if pending else "none"))
    if stopped_reason:
        print(f"stopped early: {stopped_reason}")


if __name__ == "__main__":
    main()
