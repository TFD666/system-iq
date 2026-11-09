# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

### bars

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 11 | api_style=none, database=none, architecture=none | 0 |

### clinic

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 1 | 1 | n/a | 0 | 3 | api_style=REST, database=PostgreSQL, architecture=none | 0 |

### club_events

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 2 | 0 | n/a | 0 | 8 | api_style=REST, database=none, architecture=microservices | 0 |

### handmade_store

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 1 | 0 | n/a | 0 | 4 | api_style=none, database=PostgreSQL, architecture=microservices | 0 |

### sensor_dashboard

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | n/a | 0 | 9 | api_style=REST, database=PostgreSQL, architecture=none | 0 |

### todo_sync

| version | repeat | sections_found | fallback_lines | warnings | placeholder_hits | jargon_hits | leak_hits | retries | decision_adherence | unsupported_numbers | assumption_mentions | tech_choices | jev_requests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | 13 | 0 | 1 | 0 | 0 | 3 | 0 | n/a | 0 | 9 | api_style=none, database=none, architecture=none | 0 |

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 6 | 0 |
| sections_found | 13.00 | n/a |
| fallback_lines | 0.00 | n/a |
| design_warnings | 0.17 | n/a |
| placeholder_hits | 0.00 | n/a |
| jargon_hits | 0.00 | n/a |
| unsupported_numbers | 0.00 | n/a |
| assumption_mentions | 7.33 | n/a |
| leak_hits | 1.17 | n/a |
| retries | 0.17 | n/a |
| design_prompt_tokens | 3649.83 | n/a |
| design_completion_tokens | 1235.67 | n/a |
| elapsed_seconds | 194.79 | n/a |
| jev_requests | 0.00 | n/a |
| jev_input_tokens | 0.00 | n/a |
| jev_output_tokens | 0.00 | n/a |
| flagged_count | 0.00 | n/a |
| possible_count | 0.00 | n/a |
| decision_adherence | n/a | n/a |

## Retry reasons (sum per category)

| category | A | B |
|---|---|---|
| too_short | 1 | 0 |

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
