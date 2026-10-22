# NOTES.md — System IQ

## Decisions
- V1 only, learning project, ~3 weeks. Python 3.10 + FastAPI.
- Input: inline idea string or .md/.txt file (PDF dropped: messy extraction, little learning value).
- LLM: Groq free plan, model `qwen/qwen3.8-27b`. Kept behind `LLMProvider` interface (Gemini = backup).
- Jev: planned via Vercel $5 monthly credit, behind a swappable interface. Not confirmed that Jev is covered by the free credit.
- Free-plan limits for qwen3.8-27b: 30 req/min, 1K req/day, 8K tokens/min, 200K tokens/day.
- Groq params in use: `reasoning_format: hidden`, `response_format: json_object`, `max_tokens: 1500`.
  The agent said these were "confirmed from docs", but the docs pages were JS-rendered and it
  found them via web search. Real calls succeed, so the API accepts them.

## Progress
- M1 done: CLI validation, 14 tests.
- M2 done: FastAPI /design + CLI client, 14 backend tests + 9 client tests (23 CLI total).
- Prompt D applied: null-string cleanup, "booleans only true if stated", assumptions/unknowns rules.
- Prompt E (tri-state booleans, deterministic unknowns, no invented features): FILL status
- Prompt F (redaction, notice, log-leak tests): FILL status

## Setup lessons
- Agent ran tests in the wrong venv (`Practice\venv`), causing fake pydantic conflicts.
  Fixed with fresh `.venv` at repo root; clean install passes all tests.
- `pytest` was missing from requirements. Added `requirements-dev.txt`.
- Idea file lives at `eval\idea1.md` (not `eval\ideas\`).
- Always run `git status` before commit: no `.env`, `.venv`, `eval/runs/`.

## Run consistency: bars idea, 3 runs (first data point, n=1 idea, n=3)
- Identical in all runs: all 7 booleans (geospatial true, search_filtering true, rest false),
  scale fields all null, constraints empty, user_roles ["User"], map provider integration.
- Varied: app_type (both / mobile / mobile); core_features (3, 3, 2 items; invented details
  like "ratings, hours" and "Map view" not in the idea); external_integrations wording;
  unknowns (only run 2 mentioned scale).
- Finding: structured booleans are stable, free-text lists are not.
  Build Jev questions from booleans, app_type and scale, not from the lists.
- Problem: false meant both "stated no" and "not stated". Fix = tri-state booleans (Prompt E).
- Limits: one idea, three runs, temperature unknown. Rerun after Prompt E and compare.

## Groq usage (Console logs, 2026-10-14)
- Same input, 3 runs: 497 input tokens each; output 287 / 250 / 278 (model randomness).
- Older runs: 354 in / 286 out (old prompt), 556 in / 395 out.
- Latency about 0.56 to 0.84 s. All requests returned 200, no rate limits.
- One extraction call is about 780 tokens, so about 10 calls/min and about 250 calls/day by tokens.
- Unknown: whether hidden reasoning tokens or the max_tokens cap count toward limits. FILL after checking Usage tab.
- Estimates (to verify with real numbers): M4 design call 3K-5K output tokens, full Version B run
  about 7K-13K tokens, so about 15-25 full runs/day. Eval needs several days or a second provider.

## Privacy
- Groq (read 2026-10-14, docs + secondary sources): no retention of inference data by default;
  up to 30 days reliability/abuse logs unless Zero Data Retention (ZDR) is enabled in
  console.groq.com/settings/data-controls; no training on customer data; retained data in US.
- ZDR enabled: FILL (yes/no, date)
- NOT verified: TypeSafe (Jev) data policy, Gemini free-tier data policy. Check before using.
- Layers: local-first, redaction before sending (best-effort only, regex misses things),
  one-line notice of where text goes, server never logs or stores idea text, README Privacy section.
- V2 idea only: local-model private mode (e.g. Ollama).

## Open decisions
| Decision | Resolve at | Notes |
|---|---|---|
| Free hosting for FastAPI | M2/M3 | Verify truly free; fall back to local backend |
| Jev access path | M3 | Direct SDK vs Vercel AI Gateway; confirm free credit covers Jev; Vercel route may be JS-first |
| Temperature setting | M3 | Check Groq docs for this model; do not assume low temp helps reasoning models |
| Confidence thresholds | M3 | Start simple, tune from eval |
| M4 design generation | M4 | Single call vs sections with pauses, decide from token logs |
| Eval set | M6 | Need more ideas from different domains |
