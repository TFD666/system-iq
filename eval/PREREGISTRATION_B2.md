# Pre-registration: B2 test (written before any B2 run)

Question: with the same confident writer voice, are Jev-informed designs (B2) rated differently from
LLM-only designs (A)?

Data: 6 ideas, one run per arm (A r1, B r1, B2 r1), rated blind by one rater (the author), four criteria,
1 to 5. All three designs of an idea are shown in random order, with section 13 removed.

Primary measure: for each design, the mean of its four ratings; compare B2 against A across the 6 ideas.

Reading rules, fixed now:
- B2 better: B2's overall mean is higher than A's by at least 0.30, B2 wins at least 4 of the 6 ideas, and
  B2's "correct" mean is not lower than A's.
- A better: the same in the other direction.
- Otherwise: no clear difference.

The result is reported in eval/FINDINGS.md next to the first A-vs-B result, whatever it is. No prompt, scorer
or question changes after the first B2 run starts.

Known caveats: one rater who knows the system, n = 6, free-tier models, and B2 still differs from A through
the Jev decisions it is given as fixed directives.