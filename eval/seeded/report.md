# Seeded design-validation report

n is tiny (one base design, one project idea, 9 synthetic defects, hand-written). These numbers show how Jev behaves on these specific cases, not general accuracy.

Pending variants (no result file yet): v00_base, v01_missing_component, v02_invented_feature, v03_decision_violated_api, v04_decision_violated_db, v05_scale_overclaim, v06_complexity, v07_contradiction, v08_incoherent

## Variant by question

| variant |  |
|---|

(E marks a cell where this question was expected to be flagged.)

## Per-question counts

### strict

| question | TP | FN | FP | TN | precision | recall |
|---|---|---|---|---|---|---|

### lenient

| question | TP | FN | FP | TN | precision | recall |
|---|---|---|---|---|---|---|

## Overall

- strict: TP=0 FN=0 FP=0 TN=0 precision=n/a recall=n/a
- lenient: TP=0 FN=0 FP=0 TN=0 precision=n/a recall=n/a

## Misses (strict view: expected flagged, not predicted flagged)

- none

## False positives (strict view: not expected, but predicted flagged)

- none
