# Product requirements

## Product goal

Reduce the time and effort needed to link field progress to the correct L5/L6 schedule activity while preserving enough evidence for a planner to trust each change.

## Users

- **Supervisor:** reports what started, finished, remains in progress, or is blocked without searching a large activity list.
- **Planner:** resolves uncertain reports, approves proposed actuals, and exports schedule changes.
- **Project analyst:** queries structured execution history by activity, discipline, date, and source.

## Release scope

The local prototype currently covers schedule import, text/CSV/email/selectable-text PDF reports, rule and optional AI event extraction, lexical and semantic activity suggestions, a clarification turn, planner decisions, and progress CSV export. The acceptance criteria below describe the fuller release and are not all complete.

| ID | Capability | Acceptance criterion |
| --- | --- | --- |
| R1 | Versioned schedule import | Import a synthetic XER sample; expose activity ID, name, WBS, planned dates, status, and relationships; retain the original unchanged. |
| R2 | Two field formats | Accept one free-text report and one discipline spreadsheet. Each imported row or message retains its source location. |
| R3 | Activity-level extraction | Split a report with multiple statements into separate events. Distinguish actual start, actual finish, in progress, negation, and future forecast. Preserve the original text and stated date. |
| R4 | Schedule linking | Return ranked candidate activities with ID, WBS, location, and an explanation of matching evidence. Include an explicit unmatched outcome. |
| R5 | Uncertainty handling | Ask one targeted clarification when it can disambiguate candidates; otherwise route to planner review. No candidate is silently accepted because it is first in a list. |
| R6 | Review and audit | Show old and proposed values, source evidence, warnings, reviewer, decision time, and reason. Keep immutable decision history. |
| R7 | Safe output | Stage approved actuals; produce a structured progress export. Produce an updated XER only after round-trip and import validation on a supported sample. |
| R8 | Queryable history | Search accepted and rejected events by activity, discipline, status, date, and source. |

## Behavior rules

- A finish report does not authorize inventing an unknown start date.
- A future-tense statement is a forecast, not an actual.
- A forecast or other non-actual note can be linked to an activity and retained without entering an actual-date export.
- An out-of-sequence event is preserved and flagged for review. Relationship logic is evidence, not proof that the field report is false.
- A conflict with an existing actual is reviewed; the latest report does not automatically win.
- Duplicate-looking reports are grouped for review without deleting their source records.
- Model or reranker scores are routing signals until calibrated against labeled data; they are not displayed as correctness probabilities.
- Schedule exports include only approved changes and identify their source schedule version.

## Out of initial scope

Custom speech recognition, scanned-handwriting recognition, automatic live PMIS writes, full critical-path recalculation, earned-value dashboards, delay prediction, resource leveling, and offline model deployment. The architecture keeps input and output adapters replaceable so these can be evaluated later.

## Demonstration scenarios

1. A clear text report maps to one activity and stages a dated actual with visible evidence.
2. A vague report matches two locations; the supervisor answers one question and the match is resolved.
3. A spreadsheet row conflicts with an existing actual or dependency; the planner reviews it and records a decision.
4. An unknown activity reaches the review queue as a potential new activity rather than disappearing.
5. The planner exports approved changes and sees a validation summary.
