\# Post-hoc adjudication of the 8 strict false positives



Written after seeing the results; it does not replace the original scoring in report.md.

Rule: a flag counts as a legitimate secondary defect if the mutated text really conflicts with

another section of the base design. This is the author's reading, not an independent judgment.



| variant | question | prob | verdict | reason |

|---|---|---|---|---|

| v02\_invented\_feature | val\_contradiction | 69% | plausible secondary defect | invented ratings and reviews conflict with section 13, which says this is unknown |

| v03\_decision\_violated\_api | val\_contradiction | 95% | legitimate | section 4 says GraphQL, sections 12 and 13 say REST |

| v04\_decision\_violated\_db | val\_contradiction | 72% | legitimate | section 5 says MongoDB, other sections say PostGIS |

| v05\_scale\_overclaim | val\_contradiction | 79% | plausible secondary defect | a 10 million user claim conflicts with "scale unspecified" |

| v06\_complexity | val\_contradiction | 95% | legitimate | twelve microservices conflict with the monolith decision |

| v06\_complexity | val\_incoherent | 91% | over-flag | the added sentence is clear English |

| v07\_contradiction | val\_incoherent | 84% | over-flag | the added sentence is clear English |

| v08\_incoherent | val\_contradiction | 81% | ambiguous | nonsense in section 6 may conflict with section 4 and 12 wording |



Result of this reading: 5 legitimate or plausible secondary defects, 2 over-flags, 1 ambiguous.

