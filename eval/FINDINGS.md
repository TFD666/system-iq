# System IQ V1: findings

## What was tested
Six project ideas (bars, clinic, club events, handmade store, sensor dashboard, to-do sync). Each was turned
into a 13-section system design in two ways:
- **Version A (LLM only):** Groq qwen3.8-27b extracts the requirements and writes the design, choosing the
  technologies itself.
- **Version B (pipeline):** the same LLM extracts the requirements, the Jev decision model (jev-1.13-free)
  decides REST/GraphQL, database, architecture, caching, async work and scaling, the LLM writes the design
  around those decisions, and Jev then validates the design (0.56 flagged and 0.67 possible findings per run).
n = 9 runs per version (6 ideas, 3 of them repeated). Everything ran on free tiers.

## Results
| | A | B |
|---|---|---|
| complete 13-section designs | 9 of 9 | 9 of 9 |
| placeholders, leaked jargon, unsupported numbers | 0 | 0 |
| design input tokens (mean) | 3,144 | 6,005 |
| design output tokens (mean) | 1,319 | 1,231 |
| time per design (mean) | 198 s | 191 s |
| Jev requests per run | 0 | 2 |
| decision adherence (B) | n/a | 0.96 (keyword scorer, one known false miss) |

**Blind review (one rater, 6 pairs, 1 to 5):**
| | A | B |
|---|---|---|
| specific | 4.17 | 3.00 |
| correct | 3.17 | 3.17 |
| useful | 4.00 | 2.83 |
| clear | 4.17 | 3.83 |
A was rated higher in 5 of 6 pairs. B won one pair (clinic).

**Jev decision repeatability** (3 ideas run twice): the choice was identical in every decision; mean probability
difference 0.00 to 0.05; one decision flipped from accepted (0.81) to tentative (0.71).

**Validation on seeded defects** (one clean base design, 8 hand-made defects):
| question wording | recall | precision |
|---|---|---|
| first wording | 0.89 | 0.50 |
| neutral wording | 0.78 | 0.44 |
Catches: invented features, wrong API style, wrong database, scale overclaims, incoherent text. Misses: a
removed component, once the question no longer named it. The two broad questions (contradiction, incoherent)
also flagged secondary damage that the hand-made answer key did not list.

**Revision loop:** it rewrote the flagged sections, but on a real flag (sensor design) the same flag survived
(0.82 to 0.78). Flags without a section mapping cannot be revised.

## What this shows
- Both versions produce complete, clean designs. The pipeline's extra value is confidence-labelled decisions
  and a validation report, at the price of 2 Jev requests and about twice the input tokens.
- Jev's decisions are stable on repeated input, and its validation catches stated problems reliably.
- **It does not show that Jev improves design quality. In this setup the LLM-only baseline was rated higher.**
- Validation answers depend strongly on question wording: a question naming an example flagged a design that
  passed with neutral wording.

## Limits
- One rater (the author, who knows which version is which), 6 pairs. No independent second reader.
- Tiny n, free-tier models, one LLM, synthetic defects, one base design.
- Metrics are keyword and structure counts. Adherence uses whole-word matching ("monolithic" counted as a miss
  once). The two versions also use different writer prompts (A: confident architect; B: state assumptions),
  so prompt style differs along with Jev.
- The validation question wording was changed once during the evaluation, and the first runs used the old wording.

## Next
Test a B writer prompt that is less hedged, add raters and ideas, and add per-section coherence checks so that
contradiction and incoherence flags can be revised.

## Reproduce
Raw runs are in `eval/m6/runs`, validation checks in `eval/seeded`, ratings in `eval/m6/blind`, the full
tables in `eval/m6/report.md`.
## Round 2: B2 (confident writer), tested as pre-registered in PREREGISTRATION_B2.md
B2 = the same Jev decisions and validation as B, but written in the same confident-architect voice as A, with
the decisions given as fixed directives. Uncertainty stays visible only in section 13 (hidden from raters).

| | A | B | B2 |
|---|---|---|---|
| specific | 4.83 | 3.17 | 4.67 |
| correct | 3.50 | 3.00 | 3.33 |
| useful | 4.33 | 3.17 | 4.33 |
| clear | 4.67 | 3.83 | 4.67 |
| overall mean | 4.33 | 3.29 | 4.25 |
Hedging phrases per design: A 0.56, B 8.89, B2 0.33. Design input tokens: A 3,144, B 6,005, B2 3,430.

Pre-registered rule: B2 better only if its overall mean exceeds A's by 0.30, it wins at least 4 of 6 ideas, and
its "correct" mean is not lower. Result: overall difference -0.08, wins B2 3 / A 2 / tie 1, "correct" 3.33 vs 3.50.
**No clear difference between B2 and A.**

What it shows: most of the round-1 gap between A and B came from writing voice. With voice matched, the
Jev-informed design is rated about the same as the LLM-only design, not better. The pipeline adds repeatable
decisions, a validation report and a confidence-labelled section 13, for 2 extra Jev requests and about 9% more
input tokens.

Exploratory (not pre-registered): sensor_dashboard is the only large gap (A 4.75, B2 3.25), the idea where Jev was
least confident. Without it B2 leads by 0.20, still below the pre-registered bar.

Caveats: one rater who built the system, 6 ideas, one run per arm, scores cluster at 4 and 5, absolute ratings
differ between round 1 and round 2 (rater drift).
## Round 2: B2 (confident writer), tested as pre-registered in PREREGISTRATION_B2.md
B2 = the same Jev decisions and validation as B, but written in the same confident-architect voice as A, with
the decisions given as fixed directives. Uncertainty stays visible only in section 13 (hidden from raters).

| | A | B | B2 |
|---|---|---|---|
| specific | 4.83 | 3.17 | 4.67 |
| correct | 3.50 | 3.00 | 3.33 |
| useful | 4.33 | 3.17 | 4.33 |
| clear | 4.67 | 3.83 | 4.67 |
| overall mean | 4.33 | 3.29 | 4.25 |
Hedging phrases per design: A 0.56, B 8.89, B2 0.33. Design input tokens: A 3,144, B 6,005, B2 3,430.

Pre-registered rule: B2 better only if its overall mean exceeds A's by 0.30, it wins at least 4 of 6 ideas, and
its "correct" mean is not lower. Result: overall difference -0.08, wins B2 3 / A 2 / tie 1, "correct" 3.33 vs 3.50.
**No clear difference between B2 and A.**

What it shows: most of the round-1 gap between A and B came from writing voice. With voice matched, the
Jev-informed design is rated about the same as the LLM-only design, not better. The pipeline adds repeatable
decisions, a validation report and a confidence-labelled section 13, for 2 extra Jev requests and about 9% more
input tokens.

Exploratory (not pre-registered): sensor_dashboard is the only large gap (A 4.75, B2 3.25), the idea where Jev was
least confident. Without it B2 leads by 0.20, still below the pre-registered bar.

Caveats: one rater who built the system, 6 ideas, one run per arm, scores cluster at 4 and 5, absolute ratings
differ between round 1 and round 2 (rater drift).