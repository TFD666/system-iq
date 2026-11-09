# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

(d) = detected in the category's own designated section(s); (f) = no mention there, fell back to sections 1-12.

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 0 | 4 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=2; modular monolith=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 0 | 6 | api_style=REST(d), database=none(f), architecture=modular monolith(d) | REST=1; -; modular monolith=1 | 0 |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 3 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | 5 | 1 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | 0 |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |
| A | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 4 | 0 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 6 | 1 | 0 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1,microservices=1 | 0 |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | numeric_claims | unsupported_numbers | assumption_mentions | tech_choices (scope) | tech_counts | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 3 | 1 | 1 | api_style=REST(d), database=PostgreSQL(d), architecture=modular monolith(d) | REST=1; PostgreSQL=1; modular monolith=1 | 0 |

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 9 | 0 |
| sections_found | 13.00 | n/a |
| fallback_lines | 0.00 | n/a |
| design_warnings | 0.00 | n/a |
| placeholder_hits | 0.00 | n/a |
| jargon_hits | 0.00 | n/a |
| numeric_claims | 3.22 | n/a |
| unsupported_numbers | 0.33 | n/a |
| assumption_mentions | 1.33 | n/a |
| leak_hits | 0.00 | n/a |
| retries | 0.22 | n/a |
| design_prompt_tokens | 3143.56 | n/a |
| design_completion_tokens | 1318.78 | n/a |
| elapsed_seconds | 198.42 | n/a |
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

## Unsupported numbers

For every run, each numeric claim whose number never appears in the idea text or the requirements' scale fields. Context is design text only.

### club_events__A__r1

- 256. (members): "(JWT) signed with HMAC-SHA 256. Members authenticate via email"

### sensor_dashboard__A__r1

- fifty (sensors): "data feed from approximately fifty sensors, where freshness is"

### todo_sync__A__r1

- three (users): "data model centers on three entities: Users, Lists, and"

## Consistency across repeats (fraction of tech categories identical)

| idea | version | consistency |
|---|---|---|
| bars | A | 0.67 |
| clinic | A | 1.00 |
| club_events | A | n/a |
| handmade_store | A | 1.00 |
| sensor_dashboard | A | n/a |
| todo_sync | A | n/a |

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
