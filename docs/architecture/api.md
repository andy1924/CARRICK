# API outline

This is the target interface, not the current endpoint list. The local prototype currently exposes `/api/summary`, `/api/activities`, `/api/events`, `/api/schedules/import`, `/api/reports`, `/api/events/{id}/decision`, `/api/exports`, and a CSV download route. It has no authentication or public deployment support. Use versioned routes and generated API schemas for a shared deployment.

| Method and path | Purpose | Main result |
| --- | --- | --- |
| `POST /v1/schedules/imports` | Upload a schedule and create an import job | Job ID, source checksum |
| `GET /v1/schedules/{versionId}` | Read imported schedule summary | Version, counts, validation warnings |
| `GET /v1/schedules/{versionId}/activities` | Search activities | Paginated activities and WBS context |
| `POST /v1/reports` | Submit a text report or spreadsheet | Report ID and processing job ID |
| `GET /v1/jobs/{jobId}` | Read asynchronous processing status | State, error code, result references |
| `GET /v1/reports/{reportId}/events` | Inspect extraction and matching | Events, candidates, warnings |
| `POST /v1/events/{eventId}/clarification` | Answer a disambiguation question | Updated candidate and proposal state |
| `GET /v1/review-items` | List unresolved proposals | Filterable queue |
| `POST /v1/proposals/{proposalId}/decision` | Approve, reject, or request correction | Decision and new state |
| `POST /v1/exports` | Build an approved export | Export job ID |
| `GET /v1/exports/{exportId}` | Read manifest and validation | Output link, checksum, validation results |
| `GET /v1/progress-events` | Query structured history | Paginated, discipline-tagged events |

## Contract rules

- Upload requests carry a project ID, schedule version where applicable, reporter identity, report timestamp, and timezone.
- Mutating requests accept an idempotency key. Retries return the prior result for the same key and payload.
- Review decisions require the expected proposal version to prevent two planners from approving stale values.
- Errors are machine-readable and distinguish invalid input, unsupported format, ambiguous activity, stale schedule version, permission denial, and export validation failure.
- The API never returns a success status for a schedule update that has only been staged.
- Download links are short-lived and scoped to a project and role.

## Example event response

```json
{
  "event_id": "evt_001",
  "kind": "actual_finish",
  "reported_text": "Foundation pour completed yesterday",
  "resolved_date": "2026-09-30",
  "date_precision": "day",
  "discipline": "civil",
  "source": { "report_id": "rpt_001", "row": null },
  "candidates": [
    { "activity_id": "CV-102", "rank": 1, "reason": ["foundation", "same work area"] }
  ],
  "routing": "needs_review",
  "warnings": ["actual_start_missing"]
}
```

The example uses synthetic IDs and illustrates a review case. It does not imply that a reported finish creates an actual start.
