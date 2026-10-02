# Schedule integration boundary

**Implementation status:** XER/CSV import, approved progress CSV, constrained updated XER, and validated JSON change sets are implemented. XER output is checked with a field diff and parser reimport; independent Oracle P6 acceptance has not been run.

## Import

1. Store the original schedule upload unchanged and calculate its checksum.
2. Parse only supported tables and fields into an immutable `schedule_version`.
3. Validate activity IDs, WBS references, relationship references, date parsing, and duplicate IDs.
4. Record unsupported fields and parser warnings without silently dropping the source file.
5. Make the parsed version available for matching only after structural checks pass.

The initial adapter targets a synthetic Primavera XER sample. The internal model does not expose XER table names to the web client, allowing another schedule adapter later.

## Fields initially read

- Project metadata and data date where available.
- WBS hierarchy.
- Activity ID, name, status, planned dates, actual start, actual finish, discipline and location fields when available.
- Activity relationships, relationship type, and lag.

## Proposed change set

An approved proposal targets one imported schedule version and one activity. The first write surface is limited to actual start, actual finish, and activity status when the combination is valid for the target format. Partial progress is retained in the event dataset until its mapping to a schedule percentage type is explicitly designed and tested.

## Export gate

The application offers an updated XER only when these internal checks pass:

1. The output parses again with the same supported parser.
2. Project, WBS, activity, and relationship counts match the imported version unless an approved feature explicitly changes them.
3. The diff contains only approved target fields and expected metadata.
4. Every exported actual traces to an explicit planner approval and a source report.
5. No completed activity lacks an actual start. Finish-only evidence is retained in the change set without inventing a start.

The exported manifest labels Oracle compatibility as unverified. Before importing into a master schedule, a planner must validate the output in a controlled P6 project and inspect its recalculation. The JSON change set remains available when native output is withheld or an independent import cannot be performed. Parser success is not proof of safe enterprise import.

The writer changes approved TASK actual dates, activity status, and remaining duration (to zero for a completed activity when the column exists). It retains imported TASK IDs, TASKPRED, baseline dates, calendars, and other table records. New day-precision dates serialize at 00:00; existing timestamps are retained. Partial progress and resource updates are outside this boundary. See [output details](access-output-recovery.md#schedule-output).

## Import into the system of record

Carrick does not automatically replace a master schedule. A planner chooses the import action and target in the scheduling application. Import options can update, replace, or add project data, so the operator must inspect the destination and import configuration. An exported file includes a manifest listing source checksum, output checksum, activity IDs, changed fields, approvals, and validation results.

## Schedule logic

Relationship checks explain potential conflicts: for example, a successor start preceding a predecessor finish. They do not reject an observed actual solely because it is out of sequence. The planner reviews the report and decides whether to accept the actual and how to handle schedule recalculation in the native scheduling tool.

## Version conflicts

If a newer schedule is imported while reports are pending, proposals stay attached to their original version. They must be re-matched or explicitly migrated before export against the newer schedule.
