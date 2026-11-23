# System IQ: deployment (as built, 2026-11-23)

No secrets in this file. Keys, codes and the admin token live only in the Render dashboard and a password manager.

## 1. What runs where
- **API:** Render free Docker web service `systemiq-api` (Singapore), built from the repo-root `Dockerfile` on the
  `deploy` branch. Auto-deploy is OFF: push to `deploy`, then use Manual Deploy.
  URL: https://systemiq-api-pbwg.onrender.com
- **Project page:** Render Static Site from `main`, publish directory `site`, no build command.
  URL: https://system-iq.onrender.com. Security headers (CSP, nosniff, referrer policy, permissions policy,
  cross-origin opener policy) are set in the Static Site settings; the source of truth is `site/HEADERS.md`.
- **CLI:** `pip install "git+https://github.com/TFD666/system-iq.git#subdirectory=cli"` reads `main`. Its default
  server is the API URL above; set SYSTEMIQ_API_URL=http://localhost:8000 for local development.
- **Samples:** three generated designs in `samples/` (index in `samples/index.json`), baked into the API image and
  linked from the site and the CLI (`--sample N`). Links point at `main`.
- **Rules of the two branches:** `main` = what recruiters install and what the site shows; `deploy` = what the API
  runs. Keep them merged (`git merge`), and redeploy the API manually after backend changes.

## 2. Hosted pipeline
Job mode (POST /jobs, GET /jobs/{id}); one worker thread, at most 2 waiting; results kept 60 minutes in memory.
Pipeline "B2": Groq extraction, Jev decisions, confident-voice writer, Jev validation, no auto-revision. POST /design
and /validate answer 404 when HOSTED=1. /healthz is public and free (no model calls). /admin/stats needs the admin
token and returns counts only.

## 3. Access control and quotas
- Header X-Access-Code, compared in constant time on UTF-8 bytes. Two labelled codes in ACCESS_CODES:
  `resume` (6 a day, printed publicly on the page) and `direct` (4 a day, for emails and interviews).
- Global cap 8 designs a day (DAILY_DESIGN_CAP), 2 per network (IP_DAILY_LIMIT), counted per UTC day.
  IPs are stored only as a salted hash (daily random salt). TRUSTED_PROXY_HOPS=1 was verified with runs from three
  networks (ip_hashes_today counted them separately).
- Fallbacks: Jev quota out means LLM-only designs (labelled); Groq quota out or the cap reached means the sample
  designs (CLI exit code 3). DEMO_MODE: live (default), llm_only, samples, off.
- Counters are in memory and reset when the server sleeps (accepted; worst case is extra free quota, never money).

## 4. Waking the server
Free instances sleep after 15 idle minutes and take about a minute to wake. A keep-alive cron job was tried and
removed: on 2026-11-21 all 28 pings from 08:00 to 12:10 IST got 503 with x-render-routing: hibernate-wake-error (the
app never started; cause unknown), and cron-job.org disabled the job. Now: opening the project page wakes the server
(retry up to 240 s with growing gaps, one keep-alive request every 10 minutes while the page is visible, at most 30
minutes per visit); the CLI waits up to 240 s ("Server waking up..."); if the server does not answer, the page and the
CLI point to the samples. A wake cannot be guaranteed. Before an interview, open the project page 5 minutes earlier.

## 5. Environment variable names (Render, API service)
HOSTED=1, DEMO_MODE=live, DECISION_PROVIDER=jev, DAILY_DESIGN_CAP=8, MAX_IDEA_CHARS=2000, TRUSTED_PROXY_HOPS=1,
GROQ_MODEL, JEV_MODEL, JEV_BASE_URL, GROQ_API_KEY, OPENCODE_API_KEY, ACCESS_CODES, ADMIN_TOKEN, ALLOWED_ORIGIN (the
project page's address, https, no trailing slash; set on the API service, not on the static site).
Never set ALLOW_PAID_JEV. PORT is set by Render. Hosted keys are separate from the development keys on my laptop.

## 6. Privacy
CLI shows a notice and asks to continue before every hosted run. The same redaction runs on the server. Groq: the
Inference APIs Zero Data Retention switch is enabled in the account. OpenCode free tier may use submitted text. No
cookies or accounts; logs hold counts only (no idea or design text, codes or addresses); uvicorn access logging off.

## 7. Operations
- **Change the resume code:** edit ACCESS_CODES in Render and the text in `site/index.html`, then merge to `main`.
- **Rotate keys (about every 3 months, next mid-February 2027):** create a new key at the provider, put it in Render,
  save, run one CLI test, then delete the old key. On a suspected leak: delete the key at the provider first.
- **Pause or limit the demo:** set DEMO_MODE to samples (known problem) or off (emergency) in Render and save.
- **Look at usage:** /admin/stats (admin token), the Groq usage page, the OpenCode dashboard (balance must stay $0),
  Render Events, Logs and free instance hours. Weekly, 5 minutes.
- **New samples:** `python scripts/make_sample.py` against a local server; acceptance rule in `samples/README.md`.
- **Tests:** `python -m pytest -q` (over 800, no network). Keep CLI tests in a temporary working directory.

## 8. Known limits and failure plan
- Free tiers change (hosting, Groq, OpenCode). Model names come from environment variables.
- A design takes about 3 minutes because of Groq's output-token limit.
- The resume code is public, so the caps bound the damage. 750 free instance hours a month are shared by all free web
  services in the workspace (one API service uses at most 744 in a 31-day month).
- Render ends or changes its free plan: the same Dockerfile runs on another host. Groq retires the model: change
  GROQ_MODEL. Jev free model ends: change JEV_MODEL, otherwise DEMO_MODE=samples.
- Dropped on purpose: keep-alive cron job, local read-only MCP monitor, demo video.
- The repository has no LICENSE file (decision: none).