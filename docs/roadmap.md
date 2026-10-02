# Roadmap

## Current build

The local application imports XER/CSV schedules, captures notes and logs, and exports approved progress. It includes optional cloud or local RAG, scan OCR, local vision transcription for handwritten diaries, browser microphone recording, local speech transcription, a cached workspace and device report outbox, and read-only schedule scenarios. OCR, speech, and local AI need separately provisioned engines/model files. The application now includes password accounts, per-project supervisor/planner/owner access, retained-source recovery, constrained XER output, and validated change sets. Regression and browser suites cover the implemented workflows with deterministic provider adapters. See [access, output, and recovery](architecture/access-output-recovery.md). Independent Oracle P6 import, real OCR/speech quality, production accuracy evaluation, and asynchronous processing jobs remain outstanding.

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

Implemented additions include exact duplicate source groups, review-only similarity flags, all four dependency types with conflict checks, richer paginated history, processing telemetry, and reviewed evaluation/calibration commands. The larger independently reviewed dataset, executed release-gate evaluation, and activated calibrated policy remain outstanding. See [reliability and calibration](quality/reliability-and-calibration.md).

- Build a labeled evaluation set with jargon and near-duplicate activities.
- Compare lexical, semantic, and reranked candidates.
- Add a single targeted clarification step and schedule-context warnings.
- Tune routing thresholds from measured errors.

**Exit:** evaluation results show the chosen approach's accuracy, coverage, and latency.

## Milestone 4: Approved output

- Add staged proposals, review decisions, immutable audit records, and export manifests.
- Export a structured progress dataset.
- Constrained actual-date/status XER updates and parser round-trip checks are implemented. Independent Oracle P6 import is still an external acceptance gate.

**Exit:** a planner can trace every exported field to a source report and approval; output validation is visible.

## Later candidates

Validate OCR and handwriting on representative diaries, measure speech quality in site conditions, calibrate duration forecasts, add full calendar interpretation, and harden multi-device synchronization. Additional schedule formats and live integrations remain later work.
