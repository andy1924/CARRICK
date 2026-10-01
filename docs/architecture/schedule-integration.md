# Schedule integration boundary

**Implementation status:** XER and schedule CSV import work in the local prototype. Approved field events can be exported as a progress CSV with source references. Native schedule-file updates and controlled import validation are not implemented yet.

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

An updated XER is produced only if all of these checks pass:

1. The output parses again with the same supported parser.
2. Project, WBS, activity, and relationship counts match the imported version unless an approved feature explicitly changes them.
3. The diff contains only approved target fields and expected metadata.
4. Every exported actual traces to a reviewed or safely staged proposal and a source report.
5. The file passes an independent viewer or controlled application import using the same synthetic fixture.

If the final check cannot be performed, the product offers a validated change-set export and labels XER compatibility as unverified. Never describe parser success alone as proof of safe import into an enterprise database.

## Import into the system of record

Carrick does not automatically replace a master schedule. A planner chooses the import action and target in the scheduling application. Import options can update, replace, or add project data, so the operator must inspect the destination and import configuration. An exported file includes a manifest listing source checksum, output checksum, activity IDs, changed fields, approvals, and validation results.

## Schedule logic

Relationship checks explain potential conflicts: for example, a successor start preceding a predecessor finish. They do not reject an observed actual solely because it is out of sequence. The planner reviews the report and decides whether to accept the actual and how to handle schedule recalculation in the native scheduling tool.

## Version conflicts

If a newer schedule is imported while reports are pending, proposals stay attached to their original version. They must be re-matched or explicitly migrated before export against the newer schedule.
