# M6 eval report: version A (llm_only) vs B (pipeline, hedged) vs B2 (pipeline, confident)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

(d) = detected in the category's own designated section(s); (f) = no mention there, fell back to sections 1-12.

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | n/a | n/a | 0 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=2; modular monolith=1 | -; -; - | 0 | - | n/a | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 0 | 0 | 6 | api_style=REST(d), database=none(f), architecture=modular monolith(d) | REST=1; -; modular monolith=1 | -; -; - | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 12 | 0 | 1.00 | 1.00 | 0 | 0 | 8 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=2; PostgreSQL=2; monolith=1 | -; -; modular monolith=1 | 2 | val_incoherent (revalidated) | old | n/a |
| B | 2 | 13 | 0 | 1 | 0 | 0 | 0 | 6 | 0 | 0.67 | 0.67 | 0 | 0 | 5 | api_style=REST(d), database=PostgreSQL(d), architecture=none(f) | REST=2; PostgreSQL=2; - | -; -; modular monolith=1 | 2 | val_missing_component,val_invented (own) | neutral | n/a |
| B2 | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 0 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=2; modular monolith=1 | -; -; - | 2 | val_incoherent (revalidated) | neutral | confident |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a | 3 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | -; -; - | 0 | - | n/a | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 3 | 0 | 1.00 | 1.00 | 2 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=2 | -; -; modular monolith=1,microservices=1 | 2 | - (revalidated) | old | n/a |
| B | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 | 1.00 | 7 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=1 | -; -; microservices=1 | 2 | - (own) | neutral | n/a |
| B2 | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 2 | 0 | 2 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=4 | -; -; - | 2 | - (revalidated) | neutral | confident |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a | 4 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; - | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 5 | 0 | 1.00 | 1.00 | 4 | 0 | 5 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component,val_incoherent (revalidated) | old | n/a |
| B2 | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=4,microservices=1 | -; -; microservices=1 | 2 | val_missing_component,val_incoherent (revalidated) | neutral | confident |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | -; -; - | 0 | - | n/a | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 5 | 0 | 1.00 | 1.00 | 6 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=2,GraphQL=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component (revalidated) | old | n/a |
| B | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 8 | 1 | 1.00 | 1.00 | 4 | 0 | 2 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=2; PostgreSQL=1; modular monolith=1 | REST=1,GraphQL=1,gRPC=1; -; - | 2 | val_missing_component (own) | neutral | n/a |
| B2 | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 1 | 0 | 1.00 | 1.00 | 5 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component (revalidated) | neutral | confident |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 6 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 22 | 0 | n/a | n/a | 2 | 0 | 6 | api_style=REST(d), database=DynamoDB(d), architecture=monolith(d) | REST=1,gRPC=1; PostgreSQL=1,DynamoDB=1; modular monolith=1,monolith=1 | -; -; - | 2 | val_missing_component,val_incoherent,val_contradiction,val_scale_overclaim (revalidated) | old | n/a |
| B2 | 1 | 13 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 5 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component,val_incoherent,val_contradiction,val_scale_overclaim (revalidated) | neutral | confident |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | hedging_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording | writer_style |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | n/a | n/a | 2 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; - | 0 | - | n/a | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 17 | 0 | 1.00 | 1.00 | 3 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1,MongoDB=1; modular monolith=1 | -; -; monolith=1 | 2 | - (revalidated) | old | n/a |
| B2 | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 1 | 0 | 1.00 | 1.00 | 2 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=2 | -; -; microservices=1 | 2 | - (revalidated) | neutral | confident |

## Aggregate (mean, n shown)

| metric | A | B | B2 |
|---|---|---|---|
| n | 9 | 9 | 6 |
| sections_found | 13.00 | 13.00 | 13.00 |
| fallback_lines | 0.00 | 0.00 | 0.00 |
| design_warnings | 0.00 | 1.22 | 2.33 |
| placeholder_hits | 0.00 | 0.00 | 0.00 |
| jargon_hits | 0.00 | 0.00 | 0.00 |
| numeric_claims | 3.00 | 3.11 | 3.00 |
| unsupported_numbers | 0.00 | 0.00 | 0.00 |
| assumption_mentions | 1.33 | 4.00 | 1.17 |
| leak_hits | 0.00 | 0.00 | 0.00 |
| hedging_hits | 0.56 | 8.89 | 0.33 |
| retries | 0.22 | 0.11 | 0.00 |
| design_prompt_tokens | 3143.56 | 6005.44 | 3430.00 |
| design_completion_tokens | 1318.78 | 1231.00 | 1265.50 |
| elapsed_seconds | 198.42 | 190.72 | 191.12 |
| jev_requests | 0.00 | 2.00 | 2.00 |
| jev_input_tokens | 0.00 | 2998.22 | 3095.83 |
| jev_output_tokens | 0.00 | 377.78 | 373.83 |
| flagged_count | 0.00 | 0.56 | 0.50 |
| possible_count | 0.00 | 0.67 | 0.83 |
| decision_adherence | n/a | 0.96 | 1.00 |
| decision_adherence_strict | n/a | 0.96 | 1.00 |
| decision_adherence_in_designated_section | n/a | 0.92 | 0.94 |

## Retry reasons (sum per category)

| category | A | B | B2 |
|---|---|---|---|
| missing_heading | 2 | 0 | 0 |
| too_short | 2 | 1 | 0 |

## Unsupported numbers

For every run, each numeric claim whose number never appears in the idea text or the requirements' scale fields. Context is design text only.

none

## Consistency across repeats (fraction of determinate tech categories identical)

"none"/"mixed" choices are undetermined and excluded from the comparison; "n/a" means no category was determinate in every repeat.

| idea | version | consistency |
|---|---|---|
| bars | A | 1.00 (2/2) |
| bars | B | 1.00 (2/2) |
| bars | B2 | n/a |
| clinic | A | 1.00 (3/3) |
| clinic | B | 1.00 (3/3) |
| clinic | B2 | n/a |
| club_events | A | n/a |
| club_events | B | n/a |
| club_events | B2 | n/a |
| handmade_store | A | 1.00 (3/3) |
| handmade_store | B | 0.67 (2/3) |
| handmade_store | B2 | n/a |
| sensor_dashboard | A | n/a |
| sensor_dashboard | B | n/a |
| sensor_dashboard | B2 | n/a |
| todo_sync | A | n/a |
| todo_sync | B | n/a |
| todo_sync | B2 | n/a |

## Jev decision repeatability (idea/version, >=2 repeats)

### bars (B)

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,accepted | 0.95,0.91 | True | True | 0.04 |
| primary_database | PostgreSQL + PostGIS,PostgreSQL + PostGIS | accepted,accepted | 0.98,0.96 | True | True | 0.02 |
agreement=1.00 status_agreement=1.00 mean_abs_prob_diff=0.02

### bars (B2)

n/a

### clinic (B)

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,accepted | 0.84,0.84 | True | True | 0.00 |
| primary_database | PostgreSQL,PostgreSQL | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
agreement=1.00 status_agreement=1.00 mean_abs_prob_diff=0.00

### clinic (B2)

n/a

### club_events (B)

n/a

### club_events (B2)

n/a

### handmade_store (B)

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,tentative | 0.81,0.71 | True | False | 0.10 |
| primary_database | PostgreSQL,PostgreSQL | accepted,accepted | 0.95,0.99 | True | True | 0.04 |
agreement=1.00 status_agreement=0.67 mean_abs_prob_diff=0.05

### handmade_store (B2)

n/a

### sensor_dashboard (B)

n/a

### sensor_dashboard (B2)

n/a

### todo_sync (B)

n/a

### todo_sync (B2)

n/a

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
- Validation wording changed during the evaluation; revalidated results use the neutral wording.

## Blind review round 2 (three arms)

| field | A | B | B2 |
|---|---|---|---|
| specific | 4.83 | 3.17 | 4.67 |
| correct | 3.50 | 3.00 | 3.33 |
| useful | 4.33 | 3.17 | 4.33 |
| clear | 4.67 | 3.83 | 4.67 |
| overall_mean | 4.33 | 3.29 | 4.25 |
| n | 6 | 6 | 6 |
| wins (highest overall_mean) | 2 | 0 | 3 |
ties=1
