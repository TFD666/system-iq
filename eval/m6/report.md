# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

(d) = detected in the category's own designated section(s); (f) = no mention there, fell back to sections 1-12.

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=2; modular monolith=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 0 | 6 | api_style=REST(d), database=none(f), architecture=modular monolith(d) | REST=1; -; modular monolith=1 | 0 |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 0 | 0 | 8 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(f) | REST=2; PostgreSQL=2; modular monolith=1,monolith=1 | 2 |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 3 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 2 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=microservices(d) | REST=1; PostgreSQL=1; microservices=1 | 2 |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 4 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | 0 |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 | 4 | 0 | 5 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=1; PostgreSQL=1; monolith=1 | 2 |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| B | 1 | 13 | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 | 6 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=monolith(d) | REST=2,GraphQL=1; PostgreSQL=1; monolith=1 | 2 |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 6 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| B | 1 | 13 | 0 | 3 | 0 | 0 | 0 | 0 | n/a | 2 | 0 | 6 | api_style=REST(d), database=DynamoDB(d), architecture=monolith(d) | REST=1,gRPC=1; PostgreSQL=1,DynamoDB=1; modular monolith=1,monolith=1 | 2 |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 2 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | 0 |
| B | 1 | 13 | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 | 3 | 0 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1,MongoDB=1; modular monolith=1,monolith=1 | 2 |

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 9 | 6 |
| sections_found | 13.00 | 13.00 |
| fallback_lines | 0.00 | 0.00 |
| design_warnings | 0.00 | 1.67 |
| placeholder_hits | 0.00 | 0.00 |
| jargon_hits | 0.00 | 0.00 |
| numeric_claims | 3.00 | 2.83 |
| unsupported_numbers | 0.00 | 0.00 |
| assumption_mentions | 1.33 | 4.17 |
| leak_hits | 0.00 | 0.00 |
| retries | 0.22 | 0.00 |
| design_prompt_tokens | 3143.56 | 5804.00 |
| design_completion_tokens | 1318.78 | 1160.67 |
| elapsed_seconds | 198.42 | 183.94 |
| jev_requests | 0.00 | 2.00 |
| jev_input_tokens | 0.00 | 2933.83 |
| jev_output_tokens | 0.00 | 374.17 |
| flagged_count | 0.00 | 0.50 |
| possible_count | 0.00 | 1.50 |
| decision_adherence | n/a | 1.00 |

## Retry reasons (sum per category)

| category | A | B |
|---|---|---|
| missing_heading | 2 | 0 |
| too_short | 2 | 0 |

## Unsupported numbers

For every run, each numeric claim whose number never appears in the idea text or the requirements' scale fields. Context is design text only.

none

## Consistency across repeats (fraction of tech categories identical)

| idea | version | consistency |
|---|---|---|
| bars | A | 0.67 |
| bars | B | n/a |
| clinic | A | 1.00 |
| clinic | B | n/a |
| club_events | A | n/a |
| club_events | B | n/a |
| handmade_store | A | 1.00 |
| handmade_store | B | n/a |
| sensor_dashboard | A | n/a |
| sensor_dashboard | B | n/a |
| todo_sync | A | n/a |
| todo_sync | B | n/a |

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
