# Seeded design-validation eval

A small, hand-built set of design-document defects used to see how the
Jev-backed `/validate` endpoint behaves on known problems, not to measure
general accuracy.

## What this is

`base_design.md` is one hand-written design document (13 sections) for
the project's own "nearby bars" idea, paired with the real requirements
and decisions in `eval/results/bars_live_design1.json`. `make_variants.py`
applies one small, deliberate defect to a copy of the base for each
variant -- a missing component, an invented feature, a decision the text
contradicts, an overclaimed scale, unneeded complexity, a contradiction
between sections, and incoherent text -- plus one unchanged "v00_base"
variant as a sanity check. `ground_truth.json` records which validation
question id(s) each variant is expected to flag.

## How to run the three scripts

```bash
.venv\Scripts\python.exe eval\seeded\make_variants.py
```
Writes `variants/<id>.md` and `ground_truth.json`. Safe to re-run; it
refuses to overwrite an existing variant file unless you pass `--force`.

```bash
.venv\Scripts\python.exe eval\seeded\run_seeded.py --api-url http://localhost:8000
```
Needs a running backend with a real `OPENCODE_API_KEY` configured (real
Jev calls cost quota, hence `--limit` defaulting to 3 and `--sleep`
between requests). Saves each variant's raw `/validate` response to
`results/<id>.json`; skips a variant that already has a result unless
you pass `--force`; stops immediately (without saving) if a response
isn't a real Jev run (HTTP error, `validation_status: skipped`, or a
fake/replay decision provider).

```bash
.venv\Scripts\python.exe eval\seeded\score.py
```
Reads `ground_truth.json` and whatever is in `results/`, and writes
`report.md`: a variant-by-question table, per-question and overall
TP/FN/FP/TN counts and precision/recall for both a strict view
(`status == "flagged"`) and a lenient one (`"flagged"` or `"possible"`),
plus every miss and false positive.

## Limits

- The defects are synthetic (hand-written), not real design mistakes
  pulled from a real review.
- There is one base design and one project idea -- this says nothing
  about how `/validate` behaves on a different project.
- n is tiny (9 variants). A single flip in one variant swings the
  numbers a lot; treat this as "how Jev reacted to these specific
  cases", not as an accuracy benchmark.
