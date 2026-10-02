# Roadmap

## Current build

The local application imports XER/CSV schedules, captures notes and logs, and exports approved progress. It includes optional cloud or local RAG, scan OCR, local vision transcription for handwritten diaries, browser microphone recording, local speech transcription, a cached workspace and device report outbox, and read-only schedule scenarios. OCR, speech, and local AI need separately provisioned engines/model files. The latest additions have not been tested in this session. See [capture, offline use, and analytics](architecture/capture-offline-analytics.md). It remains a local prototype without user accounts, asynchronous processing jobs, or native schedule-file output.

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

Validate OCR and handwriting on representative diaries, measure speech quality in site conditions, calibrate duration forecasts, add full calendar interpretation, and harden multi-device synchronization. Additional schedule formats and live integrations remain later work.
