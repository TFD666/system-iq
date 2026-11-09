# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 0 | 4 | api_style=REST, database=PostgreSQL, architecture=modular monolith | REST=1; PostgreSQL=2; modular monolith=1 | 0 |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 3 | 0 | 0 | api_style=REST, database=PostgreSQL, architecture=mixed | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 5 | 1 | 1 | api_style=REST, database=PostgreSQL, architecture=mixed | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST, database=PostgreSQL, architecture=microservices | REST=2; PostgreSQL=1; modular monolith=1,monolith=1,microservices=2 | 0 |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 6 | 1 | 0 | api_style=REST, database=PostgreSQL, architecture=microservices | REST=1; PostgreSQL=1; modular monolith=1,microservices=2 | 0 |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 3 | 1 | 1 | api_style=mixed, database=mixed, architecture=modular monolith | REST=2,GraphQL=2; PostgreSQL=1,SQLite=1; modular monolith=1 | 0 |

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 6 | 0 |
| sections_found | 13.00 | n/a |
| fallback_lines | 0.00 | n/a |
| design_warnings | 0.00 | n/a |
| placeholder_hits | 0.00 | n/a |
| jargon_hits | 0.00 | n/a |
| numeric_claims | 3.50 | n/a |
| unsupported_numbers | 0.50 | n/a |
| assumption_mentions | 1.00 | n/a |
| leak_hits | 0.00 | n/a |
| retries | 0.33 | n/a |
| design_prompt_tokens | 3215.00 | n/a |
| design_completion_tokens | 1354.50 | n/a |
| elapsed_seconds | 205.45 | n/a |
| jev_requests | 0.00 | n/a |
| jev_input_tokens | 0.00 | n/a |
| jev_output_tokens | 0.00 | n/a |
| flagged_count | 0.00 | n/a |
| possible_count | 0.00 | n/a |
| decision_adherence | n/a | n/a |

## Retry reasons (sum per category)

| category | A | B |
|---|---|---|
| missing_heading | 2 | 0 |
| too_short | 2 | 0 |

## Consistency across repeats (fraction of tech categories identical)

| idea | version | consistency |
|---|---|---|
| bars | A | n/a |
| clinic | A | n/a |
| club_events | A | n/a |
| handmade_store | A | n/a |
| sensor_dashboard | A | n/a |
| todo_sync | A | n/a |

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
