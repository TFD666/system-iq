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

## Getting started, step by step (Windows)

This guide assumes nothing. It was tested on Windows with Python 3.10. macOS and Linux are not tested yet.

### 1. What you need

- A Windows PC and an internet connection.
- **Python 3.10 or newer.** The install command below cannot install Python for you, because pip comes with Python.
- An access code, printed on the [project page](https://system-iq.onrender.com) (or no code at all if you only want a sample design).

No API keys and no accounts are needed.

### 2. Open PowerShell and check Python

Click Start, type `PowerShell`, and press Enter. A window opens: this is the "terminal". Type:

    python --version

- It prints `Python 3.10` or higher (for example `Python 3.12.4`): go on to step 3.
- It prints `Python 3.9` or lower, says Python was not found, or opens the Microsoft Store: install Python from
  https://www.python.org/downloads/ (tick **Add python.exe to PATH** on the first installer screen), then close
  PowerShell and open a new one. `py --version` is another way to check on Windows.

### 3. Install System IQ (once)

Paste this into PowerShell (right-click pastes in most windows) and press Enter. It works from any folder:

    python -m pip install "https://github.com/TFD666/system-iq/archive/refs/heads/main.zip#subdirectory=cli"

Then check it:

    systemiq --version

You should see `systemiq 1.0.1`. If Windows says `systemiq` is not recognized, use `python -m systemiq --version`
instead, and write `python -m systemiq` in place of `systemiq` in every command below.

### 4. Choose where the design file will go

The design is saved in the folder PowerShell is "in" when you run the command. PowerShell starts in your user folder
(for example `C:\Users\YourName`). To keep your designs together:

    mkdir system-designs
    cd system-designs

You can open that folder in File Explorer at any time with `explorer .`

### 5. Run it

Replace YOUR_CODE with the access code and put your own idea between the double quotes:

    systemiq --access-code YOUR_CODE "A mobile app that shows nearby independent bookstores on a map, with opening hours, a search by genre, and saved favourites. About 20,000 users across one city."

- A long idea, or one that contains double quotes? Save it in a text file (`notepad idea.txt`, paste, save) and run
  `systemiq --access-code YOUR_CODE idea.txt`.
- The hosted demo accepts ideas of up to 2,000 characters.
- No code? `systemiq --sample 1` (or 2 or 3) downloads a ready-made design.
- Do not put secrets or personal data in the idea (see Privacy below).

### 6. What you will see

It prints the privacy notice and asks `Continue? [y/N]`: type `y` and press Enter. A design then takes about 3 to 4
minutes. If the server was asleep you first see `Server waking up...` for up to a few minutes. This is a real run, with
the file path and the job id shortened:

    systemiq --access-code YOUR_CODE "A mobile app that shows nearby independent bookstores on a map, with opening hours, a search by genre, and saved favourites. About 20,000 users across one city."

    /\     /\
      \ _____\
       (_)-(_)
       Welcome to SystemIQ !!!
    The design will be saved to C:\Users\YourName\system-designs\system-design.md
    Before you send:
    - Your idea is sent to Groq and OpenCode (both US) to generate the design.
    - Groq: zero data retention is enabled in the account settings for this demo.
    - OpenCode free tier: may use submitted text to improve their service.
    - System IQ redacts obvious secrets, keeps your design in memory up to 60 minutes so you can download it,
      then deletes it. Nothing is written to disk. Only counts are logged.
    - Do not enter secrets, personal data, or confidential company info.
    Continue? [y/N] y
    Job: <job id> (resume with --job <job id> within 60 minutes)
    Extracting requirements
    Writing design (2/4)
    Writing design (3/4)
    Writing design (4/4)
    Done
    design written to C:\Users\YourName\system-designs\system-design.md
    design: 4 groups, 1 retries, 246.6 s, 4174/1690 tokens

    Validation:
    ID                           STATUS         PROB  SECTIONS
    ----------------------------------------------------------
    val_geospatial               ok              98%  4, 5
    val_search                   ok              97%  4
    val_decision_api_style       ok              99%  4
    val_decision_primary_data... ok              99%  5
    val_decision_architecture... ok              99%  1, 2
    val_missing_component        flagged         87%  2, 8
    val_invented                 possible        56%  2, 5
    val_contradiction            possible        46%  -
    val_unneeded_complexity      ok              23%  -
    val_scale_overclaim          ok              35%  10
    val_incoherent               ok              13%  -
    validation: flagged, 1 Jev requests
    design warnings:
      - validation: val_invented
      - validation: val_contradiction

    Requirements:
      app type: mobile
      summary: A mobile application for discovering and saving nearby independent bookstores, featuring maps, hours, search, and favorites for a local user base.
      core features:
        - Map view of nearby independent bookstores
        - Display of opening hours
        - Search by genre
        - Saved favorites list
      geospatial: yes (evidence: "nearby independent bookstores on a map")
      search_filtering: yes (evidence: "search by genre")
      unknowns:
        - realtime not specified
        - authentication not specified
        - media_storage not specified
        - payments not specified
        - offline_support not specified
        - Data source for bookstore locations and hours

    Decisions:
    ID                                 CHOICE                           PROB STATUS               ?
    -------------------------------------------------------------------------------------------------
    api_style                          REST                              99% accepted
    primary_database                   PostgreSQL + PostGIS              97% accepted
    architecture_style                 monolith                          86% accepted
    cache_needed                       uncertain                         39% uncertain
    async_processing_needed            uncertain                         32% uncertain            ?
    horizontal_scaling_needed          no                                20% no

    Questions:
      1. api_style: Which API communication style best fits this project's needs?
      2. primary_database: Which database best suits the data storage needs of this project?
      3. architecture_style: Which architecture style is most appropriate for this project's scale?
      4. cache_needed: Does this project need a caching layer to meet its performance requirements?
      5. async_processing_needed: Does this project need asynchronous or background job processing?
      6. horizontal_scaling_needed: Does this project need horizontal scaling to handle its expecte...

    model: jev-1.13-free | tokens: 752 in / 201 out

How to read it:

- `The design will be saved to ...` is where the file will be, and `design written to ...` confirms it.
- `Job: ...` is the id of your run. If you close the window, `systemiq --job <that id>` collects the result within 60
  minutes.
- The progress lines: Extracting requirements (what the tool understood from your idea), Jev deciding (the
  architecture choices), Writing design (1/4 to 4/4) and Validating.
- `design: 4 groups, 1 retries, 246.6 s, ...`: the design is written in 4 parts, `1 retries` means one part failed an
  automatic quality check and was rewritten, then the time taken and the language-model tokens used.
- **Validation** is a second opinion on the finished design. `ok` means no problem was found, `possible` means it is
  worth a look, and `flagged` means the check is fairly sure something is wrong or missing. The SECTIONS column says
  which sections of the file to read. These are hints, not errors: the design is written anyway. Read the table first;
  the `design warnings` list under it is a shorter reminder and may not repeat every finding.
- In this run, validation flagged a possible missing component in sections 2 and 8, and the `unknowns` list says the
  idea did not mention where the bookstore data comes from. That is the kind of gap worth reading about.
- **Requirements** is what the tool understood from your idea. Every item quotes your own words (the evidence).
  `unknowns` are things your idea did not say; the tool leaves them open and does not invent them.
- **Decisions** are the architecture choices with a confidence (PROB). `accepted` means a clear winner, `tentative`
  means a proposal to check, and `uncertain` means no clear answer.
- `model: jev-1.13-free` is the decision model that was used.

### 7. Where is the design, and how do I open it

The path is on the `design written to` line. Open the file with:

    notepad system-design.md

You can also double-click it in File Explorer, or use any text editor. It is a Markdown file (plain text with
headings such as `## 1. Architecture overview`) with 13 sections.

Run another idea in the same folder and the new file is called `system-design-2.md`, then `system-design-3.md`:
nothing is overwritten. To choose your own name add `--out my-design.md`; add `--force` to overwrite a file on
purpose.

### 8. If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `python` is not recognized, or the Microsoft Store opens | Python is not installed, or Windows' Store shortcut is in the way | Install Python from python.org (tick Add python.exe to PATH), then open a new PowerShell. Try `py` instead of `python`. |
| `Fatal error in launcher ... pip.exe` | The `pip` shortcut points at a Python that no longer exists | Always use `python -m pip ...` as in step 3, or reinstall Python. |
| pip reports no matching version, or mentions the Python version | Python is older than 3.10 | Install a newer Python (step 2). |
| The install hangs or times out | Slow network | Add `--default-timeout 120` after `pip install`, or try another network. |
| `systemiq` is not recognized after a successful install | The Scripts folder is not on your PATH | Open a new PowerShell window, or run `python -m systemiq ...`. |
| `Server waking up, this can take a minute or two...` | The free server sleeps when unused | Wait, up to 4 minutes. Opening the project page also wakes it. |
| `Server unavailable, try again later or see sample designs` | It did not wake in time, or the host has a problem | Try again in a few minutes. The sample designs work meanwhile. |
| `Invalid access code` | A typo, or the code has changed | Copy the code from the project page again. |
| `Daily limit reached for this network`, `for this access code`, or `Daily demo capacity reached` | The free daily limits are used up (2 per network, a few per code, 8 in total) | Try again tomorrow (the day resets at 05:30 IST). Meanwhile run `systemiq --sample 1`. The command ends with three sample links and exit code 3. |
| `Idea is too long` | More than 2,000 characters | Shorten the idea. |
| `error: ... already exists` | You used `--out` with a name that is taken | Pick another name, or add `--force` to overwrite. Without `--out` files are numbered automatically. |
| You closed PowerShell while it was running | The run continues on the server for 60 minutes | Run `systemiq --job <job id>` (the id is printed at the start). No code is needed. |
| A company or school network blocks pip or the demo | A firewall or proxy | Try another network, for example a phone hotspot. |
| Validation says `flagged` | One check suspects a problem | It is not an error: read the sections listed in the table. |

To update to a newer version, run
`python -m pip install --upgrade --force-reinstall "https://github.com/TFD666/system-iq/archive/refs/heads/main.zip#subdirectory=cli"`.
To remove it, run `python -m pip uninstall systemiq`.

macOS and Linux: not tested yet. The tool is plain Python, so it may work with `python3 -m pip` inside a virtual
environment, but this guide does not promise it.

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
