# API outline

The `/api/` routes are implemented by the local server. All project routes require a cookie session and project membership; write requests also require a CSRF token. Supervisors can capture and clarify reports; only planners or owners can import schedules, approve/reject events, or generate exports. The current API includes summary, activities, events, history, quality, analytics, capture, report submission, decisions, and CSV/XER/change-set downloads. [Access, output, and recovery](access-output-recovery.md) documents the account and recovery endpoints.

The `/v1/` table below describes a future asynchronous interface. These routes are not implemented.

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

### Implemented reliability routes

| Method and path | Result |
| --- | --- |
| `GET /api/history` | Parameterized paginated events, grouped sources, possible repeats, and decision trail |
| `POST /api/events/{id}/checks` | Checks for the currently selected `activity_id` and `event_date`, with `blocked` and `requires_reason` flags |
| `GET /api/quality/status` | Recent processing latency, failures, usage, duplicate groups, and routing-policy metadata; no inferred accuracy |

History accepts `q`, `activity`, `discipline`, `status`, `date_field` (`event_date`, `received_at`, `decided_at`), `date_from`, `date_to`, `source`, `source_query`, `duplicates` (`all`, `grouped`), `limit` (1–200), and nonnegative `offset`. Ranges are inclusive ISO dates. The response includes `events`, `total`, `limit`, `offset`, `has_more`, and `schedule_version`. Exact repeated reports return `duplicate: true`, `duplicate_of`, `duplicate_group_id`, and the existing canonical events. Decision responses can return status `duplicate`. Export consolidation can return HTTP 200 with `id: null` and no download; a new export returns HTTP 201.

Read the [reliability contracts and limitations](../quality/reliability-and-calibration.md) for identities, checks, cohort restrictions, and migration behavior.

### Target shared-deployment contracts

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
