# System IQ

Turn a project idea into a structured system design. A Python CLI sends your idea to a small FastAPI backend.
An LLM extracts the requirements, the **Jev** decision model makes bounded architecture decisions (API style,
database, architecture, caching, async work, scaling), the LLM writes a 13-section design around those
decisions, and Jev then validates the design. No application code is generated.

**Status: V1 complete. It runs locally with your own free-tier keys. A hosted demo is planned but not live.**

## How it works

    CLI (redacts secrets locally)
      -> POST /design (FastAPI)
           1. Groq LLM: extract requirements (every claim must quote the idea, else it stays unknown)
           2. Jev: decisions as probabilities (REST/GraphQL, database, architecture, cache, async, scaling)
           3. Groq LLM: write the design in 4 section groups, paced to the free-tier token limits
           4. Jev: validation questions on the finished design
      <- design markdown, decisions, validation report

- Extraction, writer, decision provider and validation sit behind small interfaces. Fake and replay versions
  exist, so most testing needs no network and no quota.
- Free-tier limits shape the design: the Groq model allows 1,000 output tokens per minute, so one design takes
  about 3 minutes and the sections are short.

## Evaluation (small and honest)

Six project ideas, LLM-only (A) against Jev-assisted designs (B with a hedged writer, B2 with a confident writer),
rated blind by one rater.

| | A | B | B2 |
|---|---|---|---|
| overall rating (1-5) | 4.33 | 3.29 | 4.25 |

A pre-registered test (`eval/PREREGISTRATION_B2.md`) found **no clear quality difference** between the LLM-only
design and the Jev-assisted design once the writing voice is matched. Jev's decisions repeat well (the same choice
every time on repeated runs). Its validation catches stated problems (invented features, a wrong database) but
missed a removed component. Full method, results and limits: [eval/FINDINGS.md](eval/FINDINGS.md).

Example output: [docs/example_design_clinic.md](docs/example_design_clinic.md)

## Run it locally

You need Python 3.10 or newer, a free Groq API key, and an OpenCode account for the free Jev model.

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements-dev.txt

(On macOS or Linux, activate with `source .venv/bin/activate`.)

Create `backend/.env` (never commit it; it is git-ignored) with the names listed in `backend/.env.example`:
`GROQ_API_KEY`, `GROQ_MODEL`, `OPENCODE_API_KEY`, `JEV_MODEL`, `JEV_BASE_URL`.

Start the server, then use the CLI in a second terminal:

    cd backend
    uvicorn app.main:app

    python cli/systemiq.py "A web app for a small clinic where patients book appointments online"
    python cli/systemiq.py idea.md --out my-design.md
    python cli/systemiq.py --dry-run "my idea"

Useful flags: `--dry-run` (shows what would be sent, sends nothing), `--no-validate`, `--mode llm_only` (no Jev),
`--json`, `--out FILE`, `--force` (overwrite the output file).

Tests need no network and no keys: `python -m pytest -q`

## Privacy

- The CLI blanks obvious secrets (API keys, emails, phone numbers, IP addresses) before anything is sent. This is
  best-effort pattern matching, not a guarantee.
- Your idea text goes to Groq (the LLM) and to OpenCode (the Jev model). Their free-tier terms apply, and
  OpenCode's free models may use submitted text to improve their service. Do not enter secrets or confidential
  information.
- The backend stores nothing, and its logs hold only counts and ids, never idea or design text.

## Known limits

- One design takes about 3 minutes (free-tier rate limits), and the sections are short for the same reason.
- Validation answers depend strongly on question wording, and the revision step rarely clears a flagged issue.
- Free tiers change, so model names come from environment variables.
- Evaluation: tiny sample, one rater, keyword-based metrics.

## Layout

`cli/` command line, `backend/` FastAPI app (`decision/`, `design/`, `validation/`), `eval/` evaluation scripts,
runs and findings, `docs/` example output, `scripts/` probes.