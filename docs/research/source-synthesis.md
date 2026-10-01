# Research synthesis

## Scope of source material

Two supplied research briefs informed this design:

- **Architecture brief:** a broad proposal covering multimodal ingestion, semantic matching, graph reasoning, formal constraints, schedule exchange, and analytics.
- **Prototype strategy brief:** a narrower plan for schedule import, text capture, matching, human review, and export, with a suggested demonstration and evaluation approach.

The original PDFs are intentionally kept outside this public repository. This document preserves the design findings without copying internal labels, source filenames, unverified numerical claims, or potentially sensitive metadata.

## Findings that shape the product

| Finding | Design response |
| --- | --- |
| Field vocabulary differs from formal activity names. | Index names with WBS, discipline, location, codes, and aliases; measure matching on realistic jargon and decoy activities. |
| One report can mention several tasks and states. | Extract separate events before activity matching. |
| Similar activities differ by a small location or equipment detail. | Use candidate retrieval followed by contextual ranking and a targeted clarification path. |
| Real progress can conflict with a planned sequence. | Preserve the reported fact and flag the schedule anomaly for a planner. |
| Uncertain automation can damage schedule trust. | Stage proposals, retain evidence, and audit decisions before export. |
| Field data is valuable after an update cycle. | Keep a structured, discipline-tagged event history independently of the schedule file. |
| Native schedule exchange is high risk. | Preserve the imported file, validate a limited diff, and test output in a separate viewer or controlled import. |

## Reconciliation of the briefs

The architecture brief recommends voice capture, scanned document understanding, temporal graph models, constraint solvers, live schedule health analytics, and edge deployment. The prototype strategy brief recommends text-first capture and concentrating on the activity-linking loop. The first release follows the narrower path because it can prove the key value with fewer unverified dependencies. The broader ideas remain research candidates, not committed features.

Both briefs favor a two-stage matcher. We treat that as a hypothesis to test against lexical and simpler semantic baselines. A cross-encoder may improve ranking, but its score is not a calibrated probability merely because it is mapped into a 0–1 range. Fixed thresholds and reported accuracy percentages from the briefs are not adopted without a labeled evaluation set.

The briefs sometimes describe dependency filtering as proving an activity cannot have happened. That is too strong for field actuals: work may progress out of sequence. Dependency state should influence candidate ranking and produce a review warning, while the source report remains intact.

One example in the prototype brief fills a missing actual start while processing a completion report. We reject that behavior. A completion statement provides a finish event; an absent start remains unknown until separately reported or reviewed.

## Research questions to answer with prototypes

1. Does contextual reranking improve top-one activity matching over lexical and embedding baselines on location-sensitive decoys?
2. What fraction of events can be staged safely at a chosen error rate, and how often does one clarification resolve ambiguity?
3. How often do spreadsheet rows contain enough date and location context to create an actual-date proposal?
4. Can the chosen XER parser and writer preserve all unrelated tables and fields through a controlled round trip?
5. Which warnings are useful to planners, and which create excessive review load?

Answers belong in the [evaluation plan](../quality/evaluation.md) with dataset versions and measured results.
