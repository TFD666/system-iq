# M6 eval report: version A (llm_only) vs version B (pipeline)

Every metric below is computed deterministically by keyword/structure matching -- no model scored any of this.

## Per idea

## Aggregate (mean, n shown)

| metric | A | B |
|---|---|---|
| n | 0 | 0 |
| sections_found | n/a | n/a |
| fallback_lines | n/a | n/a |
| design_warnings | n/a | n/a |
| placeholder_hits | n/a | n/a |
| jargon_hits | n/a | n/a |
| unsupported_numbers | n/a | n/a |
| assumption_mentions | n/a | n/a |
| design_prompt_tokens | n/a | n/a |
| design_completion_tokens | n/a | n/a |
| elapsed_seconds | n/a | n/a |
| jev_requests | n/a | n/a |
| jev_input_tokens | n/a | n/a |
| jev_output_tokens | n/a | n/a |
| flagged_count | n/a | n/a |
| possible_count | n/a | n/a |
| decision_adherence | n/a | n/a |

## Consistency across repeats (fraction of tech categories identical)

| idea | version | consistency |
|---|---|---|

## Limitations

- n is tiny (a handful of ideas, a handful of repeats each).
- Metrics are crude keyword/structure counts, not a judgment of design quality.
- Both versions use free-tier models behind one LLM and one decision provider.
- This says how these two modes behaved on these specific ideas, not a general claim about llm-only vs pipeline design quality.
