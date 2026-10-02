# Evaluation plan

The [first synthetic comparison](benchmark-2026-10-02.md) records a small end-to-end result for the optional AI path. It is not a production performance estimate.

## Dataset

Build a synthetic but structurally realistic schedule across several disciplines, locations, and repeated activity names. Create report examples with ground-truth activity IDs and event types. Include clean phrasing, abbreviations, spelling errors, multiple events, negation, future tense, missing dates, duplicate reports, conflicting actuals, and out-of-sequence work.

Separate generation from evaluation. A person should review the held-out set, especially ambiguous and unmatched cases. Do not generate every report from the same template that the matcher sees during development. Version the fixture and label files.

## Baselines and experiments

1. Exact identifiers and lexical search.
2. Lexical plus semantic retrieval.
3. Retrieval plus contextual reranking.
4. The selected matcher with and without schedule-context features.
5. Routing with and without one clarification turn.

Compare results on the same held-out cases. Report both improvement and added latency or compute cost.

## Metrics

| Metric | Definition |
| --- | --- |
| Top-one match accuracy | Correct activity is ranked first among all labeled reports. |
| Candidate recall | Correct activity appears in the candidate set before reranking. |
| Accepted-update precision | Correct activity, event type, and actual date among proposals accepted without planner correction. |
| Coverage | Share of reports that reach an accepted proposal without planner intervention. |
| Clarification resolution | Share of ambiguous reports correctly resolved after one question. |
| Extraction accuracy | Correct event type, negation, date, discipline, and event count. |
| Unmatched recall | Truly new or unlinked activities are routed to review. |
| Export integrity | Approved-only diff, successful parser round trip, and controlled external import. |
| Latency | Median and high-percentile time to receipt, proposal, and completed export. |

Accuracy and coverage should be reported together. A system that sends every item to review can achieve high accepted-update precision while offering little practical benefit.

## Release gates

- No fixture may silently mutate the imported schedule or invent an actual date.
- Every accepted update must link to source evidence and a decision record.
- Every supported fixture must pass schedule import and output validation.
- Thresholds for automatic staging must be selected on development data and evaluated once on held-out data.
- Any format or model with unverified behavior remains behind planner review.

Initial numerical targets will be set after a pilot dataset exists. The research briefs' proposed percentages and response times are not treated as achieved results.
