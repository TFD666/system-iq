# Seeded design-validation report

n is tiny (one base design, one project idea, 9 synthetic defects, hand-written). These numbers show how Jev behaves on these specific cases, not general accuracy.

## Variant by question

| variant | val_contradiction | val_decision_api_style | val_decision_architecture_style | val_decision_primary_database | val_geospatial | val_incoherent | val_invented | val_missing_component | val_scale_overclaim | val_unneeded_complexity |
|---|---|---|---|---|---|---|---|---|---|---|
| v00_base | possible 46% | ok 99% | ok 99% | ok 99% | ok 97% | ok 10% | ok 33% | ok 27% | ok 15% | ok 25% |
| v01_missing_component | possible 46% | ok 99% | ok 99% | ok 99% | ok 97% | ok 9% | ok 35% | flagged 83%E | ok 13% | ok 26% |
| v02_invented_feature | flagged 69% | ok 99% | ok 99% | ok 99% | ok 97% | ok 21% | flagged 96%E | ok 32% | ok 17% | possible 58% |
| v03_decision_violated_api | flagged 95% | flagged 22%E | ok 97% | ok 98% | ok 97% | possible 54% | possible 44% | ok 31% | ok 20% | ok 39% |
| v04_decision_violated_db | flagged 72% | ok 99% | ok 99% | flagged 31%E | ok 93% | possible 50% | possible 41% | ok 31% | ok 18% | ok 34% |
| v05_scale_overclaim | flagged 79% | ok 99% | ok 99% | ok 99% | ok 96% | possible 55% | possible 42% | ok 29% | flagged 98%E | ok 31% |
| v06_complexity | flagged 95% | ok 98% | ok 69%E | ok 98% | ok 97% | flagged 91% | possible 43% | ok 27% | ok 19% | flagged 63%E |
| v07_contradiction | flagged 91%E | ok 99% | ok 98% | ok 99% | ok 97% | flagged 84% | possible 41% | ok 28% | ok 32% | ok 28% |
| v08_incoherent | flagged 81% | ok 98% | ok 99% | ok 99% | ok 97% | flagged 99%E | possible 49% | ok 37% | ok 18% | ok 26% |

(E marks a cell where this question was expected to be flagged.)

## Per-question counts

### strict

| question | TP | FN | FP | TN | precision | recall |
|---|---|---|---|---|---|---|
| val_contradiction | 1 | 0 | 6 | 2 | 0.14 | 1.00 |
| val_decision_api_style | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_decision_architecture_style | 0 | 1 | 0 | 8 | n/a | 0.00 |
| val_decision_primary_database | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_geospatial | 0 | 0 | 0 | 9 | n/a | n/a |
| val_incoherent | 1 | 0 | 2 | 6 | 0.33 | 1.00 |
| val_invented | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_missing_component | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_scale_overclaim | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_unneeded_complexity | 1 | 0 | 0 | 8 | 1.00 | 1.00 |

### lenient

| question | TP | FN | FP | TN | precision | recall |
|---|---|---|---|---|---|---|
| val_contradiction | 1 | 0 | 8 | 0 | 0.11 | 1.00 |
| val_decision_api_style | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_decision_architecture_style | 0 | 1 | 0 | 8 | n/a | 0.00 |
| val_decision_primary_database | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_geospatial | 0 | 0 | 0 | 9 | n/a | n/a |
| val_incoherent | 1 | 0 | 5 | 3 | 0.17 | 1.00 |
| val_invented | 1 | 0 | 6 | 2 | 0.14 | 1.00 |
| val_missing_component | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_scale_overclaim | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_unneeded_complexity | 1 | 0 | 1 | 7 | 0.50 | 1.00 |

## Overall

- strict: TP=8 FN=1 FP=8 TN=73 precision=0.50 recall=0.89
- lenient: TP=8 FN=1 FP=20 TN=61 precision=0.29 recall=0.89

## Misses (strict view: expected flagged, not predicted flagged)

- v06_complexity: val_decision_architecture_style (probability 69%)

## False positives (strict view: not expected, but predicted flagged)

- v02_invented_feature: val_contradiction (probability 69%)
- v03_decision_violated_api: val_contradiction (probability 95%)
- v04_decision_violated_db: val_contradiction (probability 72%)
- v05_scale_overclaim: val_contradiction (probability 79%)
- v06_complexity: val_contradiction (probability 95%)
- v06_complexity: val_incoherent (probability 91%)
- v07_contradiction: val_incoherent (probability 84%)
- v08_incoherent: val_contradiction (probability 81%)
