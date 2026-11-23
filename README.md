# System IQ

Turn a project idea into a structured system design. A Python command-line tool sends your idea to a small
FastAPI backend. An LLM extracts the requirements, the **Jev** decision model makes bounded architecture decisions
(API style, database, architecture, caching, async work, scaling), the LLM writes a 13-section design around those
decisions, and Jev then validates the design. No application code is generated.

**Status: V1 complete. A hosted demo is live on free tiers (access codes, daily capacity limits, sample fallback),
and everything also runs locally with your own free keys.**

Project page: https://system-iq.onrender.com

## Try the hosted demo

No keys needed. Install the command-line tool and run it with an access code (I put one on my resume and in my
applications, and it is printed on the project page):

&#x20;   pip install "git+https://github.com/TFD666/system-iq.git#subdirectory=cli"
&#x20;   systemiq --access-code YOUR_CODE "A web app for a small clinic where patients book appointments online"

If the `systemiq` command is not found, run `python -m systemiq` instead.

- **No code?** `systemiq --sample 1` downloads a ready-made design (samples 1 to 3). All three are also in
&#x20; [samples/](samples/): unedited pipeline output, each with its validation result at the top.
- **It is slow on purpose:** one design takes about 3 minutes, because the free LLM tier allows about 1,000 output
&#x20; tokens per minute. The command shows progress (queued, extracting, Jev deciding, writing 1/4 to 4/4, validating)
&#x20; and prints a job id; `systemiq --job JOB_ID` collects a finished design within 60 minutes.
- **The server sleeps** after 15 idle minutes (Render free tier). Opening the project page wakes it, and the command
&#x20; also waits for it ("Server waking up..."), so the first request after a quiet period takes about a minute.
- **Daily limits:** about 8 designs a day in total, a few per access code, 2 per network. When the day's capacity or
&#x20; a free quota is used up, the command prints the three sample links and exits with code 3.
- **Useful flags:** `--yes` (skip the confirmation), `--out FILE`, `--force` (overwrite), `--dry-run` (shows what
&#x20; would be sent, contacts nothing), `--mode llm_only` (no Jev), `--json`. The access code can also come from the
&#x20; environment variable `SYSTEMIQ_ACCESS_CODE`. Exit codes: 0 success, 1 error, 3 no design generated.
- On the first run in a terminal the tool prints a small welcome message and creates one marker file
&#x20; (`welcome_shown`, no personal data) in your user config folder. Delete it or run `systemiq --welcome` to see it
&#x20; again; set `SYSTEMIQ_NO_WELCOME=1` to turn it off.

## How it works

&#x20;   CLI (redacts secrets locally, shows the privacy notice)
&#x20;     -> hosted API on Render (FastAPI): access code and daily caps, job queue, one worker
&#x20;          1. Groq LLM: extract requirements (every claim must quote the idea, otherwise it stays unknown)
&#x20;          2. Jev: decisions as probabilities (REST/GraphQL, database, architecture, cache, async, scaling)
&#x20;          3. Groq LLM: write the design in 4 section groups, paced to the free-tier token limits
&#x20;          4. Jev: validation questions on the finished design
&#x20;     <- design markdown, decisions, validation report

Built for free-tier limits: job mode (start, then poll) because a design takes minutes; a daily global cap and
per-code and per-network limits; automatic fallbacks (Jev quota out: LLM-only design, labelled; Groq quota out: the
sample designs); the same secret redaction on the server as in the CLI; counts-only logging. Extraction, writer,
decision provider and validation sit behind small interfaces, with fake and replay versions for testing without
network or quota. Over 800 automated tests run without network.

## Evaluation (small and honest)

Six project ideas, LLM-only (A) against Jev-assisted designs (B with a hedged writer, B2 with a confident writer),
rated blind by one rater (1 to 5):

| | A | B | B2 |
|---|---|---|---|
| overall rating | 4.33 | 3.29 | 4.25 |

A pre-registered test ([eval/PREREGISTRATION_B2.md](eval/PREREGISTRATION_B2.md)) found **no clear quality
difference** between the LLM-only design and the Jev-assisted design once the writing voice is matched. Jev's
decisions repeat well (the same choice in every repeated run), and its validation catches stated problems (invented
features, a wrong database) but missed a removed component. Method, results and limits:
[eval/FINDINGS.md](eval/FINDINGS.md). Example output: [docs/example_design_clinic.md](docs/example_design_clinic.md).

## Run it locally

You need Python 3.10 or newer, a free Groq API key, and an OpenCode account for the free Jev model.

&#x20;   python -m venv .venv
&#x20;   .venv\\Scripts\\activate
&#x20;   pip install -r requirements-dev.txt

(On macOS or Linux, activate with `source .venv/bin/activate`.)

Create `backend/.env` (never commit it; it is git-ignored) with `GROQ_API_KEY`, `GROQ_MODEL`, `OPENCODE_API_KEY`,
`JEV_MODEL` and `JEV_BASE_URL`. Start the server, then use the tool in a second terminal. **Point it at your own
server**, because the command-line tool talks to the hosted demo by default:

&#x20;   cd backend
&#x20;   uvicorn app.main:app

&#x20;   $env:SYSTEMIQ_API_URL = "http://localhost:8000"      # PowerShell; on macOS/Linux: export SYSTEMIQ_API_URL=http://localhost:8000
&#x20;   python cli/systemiq.py "A web app for a small clinic where patients book appointments online"
&#x20;   python cli/systemiq.py idea.md --out my-design.md

Local mode has no access codes or limits. Add `--dry-run` to see what would be sent, `--mode llm_only` to skip Jev.
Tests need no network and no keys: `python -m pytest -q`

## Privacy

Shown before every hosted run (and on the project page):

- Your idea is sent to Groq and OpenCode (both US) to generate the design.
- Groq: zero data retention is enabled in the account settings for this demo.
- OpenCode free tier: may use submitted text to improve their service.
- System IQ redacts obvious secrets, keeps your design in memory up to 60 minutes so you can download it, then deletes it. Nothing is written to disk. Only counts are logged.
- Do not enter secrets, personal data, or confidential company info.

Redaction is best-effort pattern matching, not a guarantee. The server uses no cookies or accounts, and logs never
contain idea or design text, access codes or addresses.

## Known limits

- One design takes about 3 minutes (free-tier rate limits), and the sections are short for the same reason.
- This is a portfolio demo with daily capacity limits, not a service. Free tiers can change or end.
- Validation answers depend strongly on question wording; "possible" findings are advisory, and the revision step
&#x20; rarely clears a flagged issue.
- Evaluation: six ideas, one rater who built the system, keyword-based metrics.

## Layout

`cli/` command-line tool, `backend/` FastAPI app (`decision/`, `design/`, `validation/`, `hosted/`), `eval/`
evaluation scripts, runs and findings, `samples/` generated sample designs, `site/` the project page, `docs/`
example output and notes, `scripts/` helper scripts.
