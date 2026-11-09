# Seeded design-validation report

n is tiny (one base design, one project idea, 9 synthetic defects, hand-written). These numbers show how Jev behaves on these specific cases, not general accuracy.

## Variant by question

| variant | val_contradiction | val_decision_api_style | val_decision_architecture_style | val_decision_primary_database | val_geospatial | val_incoherent | val_invented | val_missing_component | val_scale_overclaim | val_unneeded_complexity |
|---|---|---|---|---|---|---|---|---|---|---|
| v00_base | possible 46% | ok 99% | ok 99% | ok 99% | ok 97% | ok 10% | ok 30% | ok 30% | ok 14% | ok 26% |
| v01_missing_component | possible 46% | ok 99% | ok 99% | ok 99% | ok 97% | ok 9% | ok 28% | ok 27%E | ok 15% | ok 26% |
| v02_invented_feature | flagged 72% | ok 99% | ok 99% | ok 99% | ok 97% | ok 21% | flagged 95%E | possible 54% | ok 16% | possible 59% |
| v03_decision_violated_api | flagged 95% | flagged 25%E | ok 97% | ok 97% | ok 97% | possible 59% | ok 39% | ok 36% | ok 18% | possible 41% |
| v04_decision_violated_db | flagged 72% | ok 99% | ok 99% | flagged 31%E | ok 94% | possible 49% | ok 36% | ok 38% | ok 16% | ok 33% |
| v05_scale_overclaim | flagged 81% | ok 99% | ok 99% | ok 99% | ok 97% | flagged 60% | ok 39% | ok 31% | flagged 98%E | ok 31% |
| v06_complexity | flagged 95% | ok 98% | ok 68%E | ok 98% | ok 97% | flagged 92% | ok 35% | ok 34% | ok 20% | flagged 67%E |
| v07_contradiction | flagged 92%E | ok 98% | ok 98% | ok 99% | ok 97% | flagged 87% | ok 35% | ok 31% | ok 31% | ok 29% |
| v08_incoherent | flagged 82% | ok 98% | ok 99% | ok 98% | ok 96% | flagged 99%E | ok 34% | possible 47% | ok 17% | ok 27% |

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
| val_incoherent | 1 | 0 | 3 | 5 | 0.25 | 1.00 |
| val_invented | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_missing_component | 0 | 1 | 0 | 8 | n/a | 0.00 |
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
| val_invented | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_missing_component | 0 | 1 | 2 | 6 | 0.00 | 0.00 |
| val_scale_overclaim | 1 | 0 | 0 | 8 | 1.00 | 1.00 |
| val_unneeded_complexity | 1 | 0 | 2 | 6 | 0.33 | 1.00 |

## Overall

- strict: TP=7 FN=2 FP=9 TN=72 precision=0.44 recall=0.78
- lenient: TP=7 FN=2 FP=17 TN=64 precision=0.29 recall=0.78

## Misses (strict view: expected flagged, not predicted flagged)

- v01_missing_component: val_missing_component (probability 27%)
- v06_complexity: val_decision_architecture_style (probability 68%)

## False positives (strict view: not expected, but predicted flagged)

- v02_invented_feature: val_contradiction (probability 72%)
- v03_decision_violated_api: val_contradiction (probability 95%)
- v04_decision_violated_db: val_contradiction (probability 72%)
- v05_scale_overclaim: val_contradiction (probability 81%)
- v05_scale_overclaim: val_incoherent (probability 60%)
- v06_complexity: val_contradiction (probability 95%)
- v06_complexity: val_incoherent (probability 92%)
- v07_contradiction: val_incoherent (probability 87%)
- v08_incoherent: val_contradiction (probability 82%)
