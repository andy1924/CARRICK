# Decision 0001: Stage actuals before export

**Status:** Accepted for the initial architecture

## Context

Field reports can be vague, duplicated, contradictory, or out of sequence. A wrong activity match or inferred date can damage confidence in the schedule and be difficult to reverse after import.

## Decision

Carrick stores source reports and extracted events first. It then creates update proposals tied to a schedule version. Clear proposals can be staged automatically; uncertain or conflicting proposals require planner review. Only approved proposals enter an export. The original schedule remains immutable.

## Consequences

- The UI must distinguish submitted, staged, approved, and exported states.
- The data model needs proposal, decision, and manifest records.
- Export is slower than a direct database write but remains reviewable and reproducible.
- A future live integration must preserve the same proposal and approval boundary unless a new decision record explicitly changes it.
