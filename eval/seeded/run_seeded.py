"""
Send every seeded variant to a running backend's POST /validate and save
the raw response to eval/seeded/results/<id>.json.

Real network calls on purpose (this is the eval harness, not a test) --
--limit and --sleep exist specifically to keep that bounded and polite.

Stops immediately, without saving, on any sign the run wasn't a real
Jev call: non-200, meta.validation_status == "skipped", or
meta.decision_model containing "fake"/"replay". Prints only ids,
statuses, and counts -- never the design text.
"""

import argparse
import json
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
DEFAULT_FROM = Path("eval/results/bars_live_design1.json")
VARIANTS_DIR = HERE / "variants"
RESULTS_DIR = HERE / "results"

REQUEST_TIMEOUT = 120.0


def _read_json_bom(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def load_requirements_and_decisions(path: Path) -> tuple[dict, list]:
    data = _read_json_bom(path)
    requirements = data.get("requirements")
    if not isinstance(requirements, dict):
        raise ValueError(f"{path}: missing 'requirements'")
    return requirements, data.get("decisions") or []


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the seeded design variants against /validate.")
    parser.add_argument("--from", dest="from_file", default=str(DEFAULT_FROM), metavar="PATH")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=3, help="Max real requests this run.")
    parser.add_argument("--sleep", type=float, default=5.0, help="Seconds between requests.")
    parser.add_argument("--only", default=None, help="Comma-separated variant ids to run.")
    parser.add_argument("--force", action="store_true", help="Re-run variants that already have a result.")
    args = parser.parse_args()

    requirements, decisions = load_requirements_and_decisions(Path(args.from_file))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    variant_ids = sorted(p.stem for p in VARIANTS_DIR.glob("*.md"))
    if args.only:
        wanted = set(args.only.split(","))
        variant_ids = [v for v in variant_ids if v in wanted]

    requests_used = 0
    stopped_reason = None
    pending_candidates: list[str] = []

    for index, variant_id in enumerate(variant_ids):
        result_path = RESULTS_DIR / f"{variant_id}.json"
        if result_path.exists() and not args.force:
            print(f"skip (already has a result): {variant_id}")
            continue

        if requests_used >= args.limit:
            print(f"stop: request limit ({args.limit}) reached")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"request limit ({args.limit}) reached"
            break

        design_markdown = (VARIANTS_DIR / f"{variant_id}.md").read_text(encoding="utf-8")

        if requests_used > 0:
            time.sleep(args.sleep)

        try:
            response = httpx.post(
                f"{args.api_url.rstrip('/')}/validate",
                json={
                    "requirements": requirements,
                    "decisions": decisions,
                    "design_markdown": design_markdown,
                    "max_revisions": 0,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            print(f"stop: {variant_id}: request failed ({type(exc).__name__})")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"request failed for {variant_id}"
            break

        requests_used += 1

        if response.status_code != 200:
            print(f"stop: {variant_id}: HTTP {response.status_code}")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"HTTP {response.status_code} on {variant_id}"
            break

        body = response.json()
        meta = body.get("meta") or {}
        status = meta.get("validation_status")
        validation_model = meta.get("validation_model")
        model_label = str(validation_model or "").lower()

        if status == "skipped":
            print(f"stop: {variant_id}: validation_status is skipped")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"validation skipped on {variant_id}"
            break

        # decision_model is fixed to "n/a (validation only)" on /validate,
        # so validation_model (plus a real token count) is what tells a
        # real Jev run apart from fake/replay/a provider that didn't run.
        if not validation_model:
            print(f"stop: {variant_id}: validation_model missing, not a real Jev run; not saving")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"validation_model missing on {variant_id}"
            break

        if "fake" in model_label or "replay" in model_label:
            label = "fake" if "fake" in model_label else "replay"
            print(f"stop: {variant_id}: decision provider is {label}, not a real Jev run; not saving")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"{label} decision provider on {variant_id}"
            break

        if not meta.get("validation_input_tokens"):
            print(f"stop: {variant_id}: validation_input_tokens is 0 or missing, not a real Jev run; not saving")
            pending_candidates.extend(variant_ids[index:])
            stopped_reason = f"zero validation_input_tokens on {variant_id}"
            break

        result_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
        print(f"saved: {variant_id}: status={status}")

    pending = [v for v in pending_candidates if not (RESULTS_DIR / f"{v}.json").exists()]

    print(f"requests used: {requests_used}")
    print("pending: " + (", ".join(pending) if pending else "none"))
    if stopped_reason:
        print(f"stopped early: {stopped_reason}")


if __name__ == "__main__":
    main()
