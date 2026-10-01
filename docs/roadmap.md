# Roadmap

## Current build

The local application already loads a synthetic XER schedule or a schedule CSV, accepts text and discipline CSV reports, extracts events with deterministic rules, ranks candidate activities lexically, records planner decisions, and exports approved events as a progress CSV. Five automated checks cover the central parsing and review-to-export behavior. It is a local prototype without user accounts, asynchronous jobs, semantic reranking, or native schedule-file output.

## Milestone 1: Schedule foundation

- Create one synthetic schedule fixture with repeated activity names across locations.
- Import and version its activities, WBS, and relationships.
- Display import validation results and a searchable activity list.
- Document the exact supported XER variant and parser behavior.

**Exit:** the same source file imports deterministically and remains unchanged.

## Milestone 2: Report-to-event loop

- Add supervisor text entry and discipline spreadsheet ingestion.
- Extract multiple event claims with date and tense handling.
- Preserve original report and row-level provenance.
- Add exact and lexical matching, explicit unmatched routing, and planner review.

**Exit:** clear, ambiguous, contradictory, and unknown examples each take the expected path.

## Milestone 3: Better matching and clarification

- Build a labeled evaluation set with jargon and near-duplicate activities.
- Compare lexical, semantic, and reranked candidates.
- Add a single targeted clarification step and schedule-context warnings.
- Tune routing thresholds from measured errors.

**Exit:** evaluation results show the chosen approach's accuracy, coverage, and latency.

## Milestone 4: Approved output

- Add staged proposals, review decisions, immutable audit records, and export manifests.
- Export a structured progress dataset.
- Attempt limited XER updates and verify round-trip plus independent import on synthetic fixtures.

**Exit:** a planner can trace every exported field to a source report and approval; output validation is visible.

## Later candidates

Scanned diary extraction, native voice capture, additional schedule formats, live integrations, forecasting, advanced schedule analytics, and offline operation. Each requires a separate evidence-based decision.
