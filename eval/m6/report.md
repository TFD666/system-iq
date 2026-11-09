# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

(d) = detected in the category's own designated section(s); (f) = no mention there, fell back to sections 1-12.

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 0 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=2; modular monolith=1 | -; -; - | 0 | - | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 0 | 0 | 6 | api_style=REST(d), database=none(f), architecture=modular monolith(d) | REST=1; -; modular monolith=1 | -; -; - | 0 | - | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 0 | 0 | 8 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=2; PostgreSQL=2; monolith=1 | -; -; modular monolith=1 | 2 | val_incoherent (revalidated) | old |
| B | 2 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 0.67 | 0.67 | 0 | 0 | 5 | api_style=REST(d), database=PostgreSQL(d), architecture=none(f) | REST=2; PostgreSQL=2; - | -; -; modular monolith=1 | 2 | val_missing_component,val_invented (own) | neutral |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a | 3 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | -; -; - | 0 | - | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 2 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=2 | -; -; modular monolith=1,microservices=1 | 2 | - (revalidated) | old |
| B | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 7 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=1; PostgreSQL=1; monolith=1 | -; -; microservices=1 | 2 | - (own) | neutral |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a | 4 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; - | 0 | - | n/a |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 4 | 0 | 5 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component,val_incoherent (revalidated) | old |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | -; -; - | 0 | - | n/a |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 6 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=2,GraphQL=1; PostgreSQL=1; monolith=1 | -; -; - | 2 | val_missing_component (revalidated) | old |
| B | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 | 1.00 | 4 | 0 | 2 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=2; PostgreSQL=1; modular monolith=1 | REST=1,GraphQL=1,gRPC=1; -; - | 2 | val_missing_component (own) | neutral |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 6 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; microservices=1 | 0 | - | n/a |
| B | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 0 | n/a | n/a | 2 | 0 | 6 | api_style=REST(d), database=DynamoDB(d), architecture=monolith(d) | REST=1,gRPC=1; PostgreSQL=1,DynamoDB=1; modular monolith=1,monolith=1 | -; -; - | 2 | val_missing_component,val_incoherent,val_contradiction,val_scale_overclaim (revalidated) | old |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | decision_adherence_strict | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | tech_ignored | jev_requests | non_ok_ids (source) | wording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | n/a | 2 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | -; -; - | 0 | - | n/a |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 1.00 | 3 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1,MongoDB=1; modular monolith=1 | -; -; monolith=1 | 2 | - (revalidated) | old |

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 9 | 9 |
| sections_found | 13.00 | 13.00 |
| fallback_lines | 0.00 | 0.00 |
| design_warnings | 0.00 | 1.22 |
| placeholder_hits | 0.00 | 0.00 |
| jargon_hits | 0.00 | 0.00 |
| numeric_claims | 3.00 | 3.11 |
| unsupported_numbers | 0.00 | 0.00 |
| assumption_mentions | 1.33 | 4.00 |
| leak_hits | 0.00 | 0.00 |
| retries | 0.22 | 0.11 |
| design_prompt_tokens | 3143.56 | 6005.44 |
| design_completion_tokens | 1318.78 | 1231.00 |
| elapsed_seconds | 198.42 | 190.72 |
| jev_requests | 0.00 | 2.00 |
| jev_input_tokens | 0.00 | 2998.22 |
| jev_output_tokens | 0.00 | 377.78 |
| flagged_count | 0.00 | 0.56 |
| possible_count | 0.00 | 0.67 |
| decision_adherence | n/a | 0.96 |
| decision_adherence_strict | n/a | 0.96 |
| decision_adherence_in_designated_section | n/a | 0.92 |

## Retry reasons (sum per category)

| category | A | B |
|---|---|---|
| missing_heading | 2 | 0 |
| too_short | 2 | 1 |

## Unsupported numbers

For every run, each numeric claim whose number never appears in the idea text or the requirements' scale fields. Context is design text only.

none

## Consistency across repeats (fraction of determinate tech categories identical)

"none"/"mixed" choices are undetermined and excluded from the comparison; "n/a" means no category was determinate in every repeat.

| idea | version | consistency |
|---|---|---|
| bars | A | 1.00 (2/2) |
| bars | B | 1.00 (2/2) |
| clinic | A | 1.00 (3/3) |
| clinic | B | 1.00 (3/3) |
| club_events | A | n/a |
| club_events | B | n/a |
| handmade_store | A | 1.00 (3/3) |
| handmade_store | B | 0.67 (2/3) |
| sensor_dashboard | A | n/a |
| sensor_dashboard | B | n/a |
| todo_sync | A | n/a |
| todo_sync | B | n/a |

## Jev decision repeatability (idea, >=2 B repeats)

### bars

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,accepted | 0.95,0.91 | True | True | 0.04 |
| primary_database | PostgreSQL + PostGIS,PostgreSQL + PostGIS | accepted,accepted | 0.98,0.96 | True | True | 0.02 |
agreement=1.00 status_agreement=1.00 mean_abs_prob_diff=0.02

### clinic

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,accepted | 0.84,0.84 | True | True | 0.00 |
| primary_database | PostgreSQL,PostgreSQL | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
agreement=1.00 status_agreement=1.00 mean_abs_prob_diff=0.00

### club_events

n/a

### handmade_store

| decision_id | choices (by repeat) | statuses (by repeat) | probabilities (by repeat) | match | status_match | abs_prob_diff |
|---|---|---|---|---|---|---|
| api_style | REST,REST | accepted,accepted | 1.00,1.00 | True | True | 0.00 |
| architecture_style | monolith,monolith | accepted,tentative | 0.81,0.71 | True | False | 0.10 |
| primary_database | PostgreSQL,PostgreSQL | accepted,accepted | 0.95,0.99 | True | True | 0.04 |
agreement=1.00 status_agreement=0.67 mean_abs_prob_diff=0.05

### sensor_dashboard

n/a

### todo_sync

n/a

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
- Validation wording changed during the evaluation; revalidated results use the neutral wording.

## Blind review ratings (revealed)

| field | A | B |
|---|---|---|
| specific | 4.17 | 3.00 |
| correct | 3.17 | 3.17 |
| useful | 4.00 | 2.83 |
| clear | 4.17 | 3.83 |
| n | 6 | 6 |
