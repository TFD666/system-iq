# System IQ: deployment plan (hosted demo)

Source: hosting chat handoff (2026-11-09), adapted to the actual code (2026-11-10). No secrets in this file.
[V] = verified with a source when read. [U] = unverified, check before relying on it.

## 1. Goal and hard rules
- Portfolio demo, not a service for the public. Hosted on my own free-tier keys so a recruiter can try it
  without keys when I am not around. The repo is public but not promoted; the resume links to it.
- Hard rule: zero cost and no card anywhere. If a piece cannot be free, redesign it, never pay.
- Hosted pipeline = B2: Jev decisions + Jev validation, confident writer, max_revisions 0.
  Fallback = LLM-only pipeline when Jev is unavailable, labelled in the output.
- Resume wording: "hosted demo on free tier with access codes, daily capacity limits and sample fallback".
  Never "production-ready", "scalable" or "serves users".

## 2. Host
- Render free web service from a Dockerfile (512 MB RAM, 750 hours a month, 100 min request timeout,
  sleeps after 15 idle minutes, about 1 minute to wake) [V]. Stay on the Free instance type. If any page asks
  for a card or payment method: stop.
- Rejected [V]: Koyeb (card), Hugging Face Docker Spaces (paid), Fly.io (no free tier), Vercel (serverless).
- Backup for live interviews only: laptop plus Cloudflare Quick Tunnel (random URL, no uptime guarantee).
- Run uvicorn with one worker and no access log (in-memory state; raw IPs stay out of our logs).

## 3. Wake-up
- Static site (separate Render static service, folder site/): on load calls GET /healthz once, polls every
  5 s for up to about 90 s, shows "waking server" then "ready". It works even if the call fails.
- Daytime keep-alive: cron-job.org pings /healthz every 10 minutes, 08:00-23:00 IST (about 465 hours a month).
- /healthz returns {"status":"ok","hosted":true}. No Groq or Jev call, no per-hit logging, no rate limit.
- CORS allows only the static site origin (ALLOWED_ORIGIN).
- CLI: GET /healthz with a 5 s timeout; if slow print "Server waking up, this can take up to 1 minute...",
  retry every 5 s up to 90 s, then "Server unavailable, try again later or see sample designs: <links>".

## 4. Job mode (one design is about 3 minutes)
- POST /jobs returns 202 {job_id} (uuid4). GET /jobs/{id} returns status (queued, running, done, failed,
  sample), stage, queue position and the result.
- One background worker THREAD with a queue and a lock-guarded status dict (the pipeline is blocking code;
  do not run it inside an async handler). At most 2 waiting, a 4th request gets "busy".
- Stages shown by the CLI: Queued, Extracting, Jev deciding, Writing (1/4 to 4/4), Validating, Done.
- Results stay in memory for 60 minutes, then are deleted. Restart loses jobs; the CLI says so.
- `--job <id>` collects a result within 60 minutes.
- The result carries everything the CLI needs to write the same file as the local flow.
- POST /design and POST /validate stay for local use and tests; both are disabled when HOSTED=1.
- Hosted jobs always run pipeline "validate" with writer_style "confident" and max_revisions 0.
- The pipeline is first refactored into run_pipeline(request, on_stage) so both /design and the job worker use it.

## 5. Access control (no accounts)
- Header X-Access-Code. ACCESS_CODES = "label:code:daily_limit,..." with two codes: resume (6 a day, printed
  publicly) and direct (4 a day, for emails and interviews). Labels let me see usage per channel and revoke one.
  Compare codes and the admin token in constant time (hmac.compare_digest). Never log a code, only its label.
- Per IP: 2 designs a day, using a salted hash of the IP (random in-memory daily salt). [U] Read the right
  X-Forwarded-For entry on Render and verify after deploy.
- Global cap DAILY_DESIGN_CAP = 8, tuned after a week. The day is UTC (reset 05:30 IST, same as Jev).
- DEMO_MODE (set manually in the Render dashboard): live (default), llm_only, samples, off.
- Automatic fallbacks while live:
  - Jev decisions quota exhausted: continue as LLM-only, labelled "generated without Jev decisions".
  - Jev validation quota exhausted: deliver the design with "validation skipped" (already how the code behaves).
  - Groq daily quota exhausted, or global cap hit: samples, until the 05:30 IST reset.
- Check order, cheapest first: code, mode, idea size, IP limit, code limit, global cap, queue, run.
- Failures caused by the app do not use up the visitor's per-IP or per-code run; they still count to the global cap.
- Counters live in memory and reset when the server sleeps (accepted: worst case is extra free quota, never money).
- Messages: bad code, IP limit reached, "Daily demo capacity reached. Try after 05:30 IST, or see sample
  designs: <link>", "Server busy, try in about 5 minutes", samples/off notices.

## 6. Quota protection and limits
- Idea max 2000 characters for hosted use (env MAX_IDEA_CHARS, local default 20000), checked in the CLI and on
  the server. The same redactor runs on the server (a copy of cli/redact.py in backend/app, plus a test that
  both files are identical).
- Keep the existing waits that honour Groq retry-after and the short retries on 5xx. No retry on Jev quota errors.
- Each hosted design is about 5.5K Groq tokens (limit 200K a day) and 2 Jev requests. Cap 8 means 16 Jev requests;
  we measured dozens in a day, so it is fine, and the fallbacks above cover the unknown.
- Money safety: no card on Render, Groq or OpenCode. Confirm OpenCode balance is 0 with no auto top-up.
  ALLOW_PAID_JEV stays unset. Model names come from environment variables.

## 7. Samples
- Three samples in samples/: a location app, a real-time app, a simple CRUD app. Made by running the real
  pipeline locally, unedited. Written rule: accept a run if the automatic checks pass (13 sections, no fallback
  lines, no warnings); regenerate only on those objective failures, and say so in the README.
- Each starts with "SAMPLE: generated by System IQ on <date> (pipeline vX), not generated from your input."
- Opened through GitHub file links. Shown when DEMO_MODE=samples, the cap is hit, a quota is out, or the server
  is unreachable. The CLI prints the reason and 3 links, writes no file, and `--sample N` downloads one.

## 8. Interface
- No try-it form on the site. Hosted runs come from the CLI only.
- The static site is the front door: what it is, how it works, the demo video, how to try it (install plus
  code), the privacy notice, 3 sample links, the source link. Plain HTML, CSS and a little JavaScript.
- CLI default server is the hosted URL. Setting SYSTEMIQ_API_URL overrides it (I set it to
  http://localhost:8000 on my laptop permanently, so my own runs never use the demo's limits).
- CLI additions: --access-code, job polling, wake handling, --job, --sample N, --yes; a Y/N privacy prompt
  before every hosted run (none in local mode).
- CLI packaging: pyproject.toml with a `systemiq` command, installable from GitHub (path to confirm).
  The CLI detects hosted mode from /healthz and uses the jobs flow; otherwise the existing /design flow.

## 9. Secrets
- Keys only in the Render dashboard (Environment). Never in the repo, image, site or logs.
- Hosted keys are separate from my dev keys. One Groq account and one OpenCode account: a second account for
  extra quota breaks Groq's acceptable use policy [V], so do not.
- Groq: look for a Zero Data Retention switch in Data Controls [U: earlier the page showed only Batch and
  Fine-tuning]. Without it, the notice says "Groq may keep logs up to 30 days".
- ADMIN_TOKEN is random: python -c "import secrets; print(secrets.token_urlsafe(32))". Never paste it anywhere.
- Rotate keys about every 3 months. On a leak: delete the key at the provider first, then create a new one,
  update Render, test once, and clean git if needed.
- .env stays git-ignored and .dockerignore excludes it. Check GitHub push protection in repo settings [U].

## 10. Privacy
- Notice and Y/N prompt before each hosted run (same text on the site and in the README):
  - Your idea is sent to Groq and OpenCode (both US) to generate the design.
  - Groq retention: state only what is verified (see section 9).
  - OpenCode free tier: may use submitted text to improve their service.
  - System IQ redacts obvious secrets, keeps your design in memory up to 60 minutes so you can download it,
    then deletes it. Nothing is written to disk. Only counts are logged.
  - Do not enter secrets, personal data or confidential company information.
- Logged: job start and end, stage durations, code label, status codes, token counts, cap counts. Never logged:
  idea or design text, codes, raw IPs, keys, headers. The error handler logs the error class and stage only.
- Render's own platform logs may record IPs and paths (outside our control) [U].

## 11. Monitoring and packaging
- GET /admin/stats (header X-Admin-Token): counts only. scripts/stats.ps1 reads the token from the user
  environment variable SIQ_ADMIN_TOKEN. Log lines CAP_80 and CAP_HIT. cron-job.org failure email [U].
- After deploy: a local read-only MCP monitor (tools/mcp_monitor, stdio, tools get_stats and check_health).
- Dockerfile in backend/ (python:3.10-slim, pinned requirements, non-root user, uvicorn on $PORT, one worker,
  no access log); .dockerignore excludes .env, .venv, tests, .git, eval/.
- Demo video: 60-90 seconds of a real CLI run (wait sped up, nothing faked), unlisted on YouTube, embedded on the site.
- README gains: hosted try-it, limits, privacy. No posts or topic tags until I decide.

## 12. Env var names, build order, rules
Names (hosted): GROQ_API_KEY, OPENCODE_API_KEY, GROQ_MODEL, GROQ_DESIGN_MODEL, JEV_MODEL, JEV_BASE_URL,
DECISION_PROVIDER (jev), ACCESS_CODES, ADMIN_TOKEN, DAILY_DESIGN_CAP (8), DEMO_MODE (live), HOSTED (1),
ALLOWED_ORIGIN, MAX_IDEA_CHARS (2000), DESIGN_TPM, DESIGN_OTPM. Never set: ALLOW_PAID_JEV.
Local only: SIQ_ADMIN_TOKEN, SYSTEMIQ_API_URL.

Build order (one agent prompt per step: verify, then commit):
0. V1 wrap-up (done): tag v1.0, branch deploy.
1. My hands only: Render Free card check, Groq Data Controls check, hosted keys, ADMIN_TOKEN, the two codes.
2. Backend: pipeline refactor; HOSTED config, /healthz, CORS; job mode; access, caps, DEMO_MODE and fallbacks;
   samples; server redaction, safe errors, counts-only logs; /admin/stats.
3. CLI: packaging, then the hosted flow.
4. Dockerfile, local docker run test.
5. Generate the 3 samples.
6. Render deploy, env vars, X-Forwarded-For check.
7. Static site, cron-job.org.
8. Demo video, README, resume wording, stats.ps1, MCP monitor.
Agent rules: project venv only, install nothing without asking, no real network in tests, never write to real
files in tests (tmp_path), paste the final pytest summary line, show exact files changed, never print or open
.env, read git status before every git add.

Open risks: card prompt on the Free instance type; Jev daily allowance unknown; X-Forwarded-For handling;
free tiers change (keep Docker and environment-variable model names); the resume code is effectively public
(the caps bound the damage); counters reset on sleep.