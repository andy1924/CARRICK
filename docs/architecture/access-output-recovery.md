# Access, schedule output, and recovery

## Local setup

Run `python3 -m services.api.app` or use the project virtual environment. Open `/app` and create the first owner account. There are no default credentials. Existing schedules, reports, captures, and exports are assigned to the initial project during the additive migration. The first owner receives access to that project. Complete setup on the host before exposing the service.

Use **Project access** to create a project, add a supervisor/planner account, change an existing member’s role, or remove access. Adding an existing email grants membership without resetting that account’s password. Owners cannot be removed through this form. Users can change their own password; that invalidates their other sessions. A second account requires an owner-provided initial password shared through a secure channel. Email verification, password-reset email, SSO, and MFA are not implemented.

## Authorization

| Capability | Supervisor | Planner | Owner |
| --- | --- | --- | --- |
| Read project schedule, reports, history, source files, and exports | Yes | Yes | Yes |
| Submit text, document, or voice reports; retry or clarify | Yes | Yes | Yes |
| Import schedules and load a sample | No | Yes | Yes |
| Approve/reject events and generate exports | No | Yes | Yes |
| Manage project membership | No | No | Yes |

All project API requests require membership. Imports, decisions, and export generation require planner or owner access. Resource identifiers are checked against their project, including capture originals and export downloads. The API rechecks membership on each request, so revocation applies to existing sessions. Audit actors come from the authenticated account, with a user ID in the decision/clarification detail. Client-supplied actor labels do not determine HTTP audit identity. Every authenticated account can create a project and becomes its owner.

Passwords use salted scrypt (`N=131072`, `r=8`, `p=1`). Concurrent hashing is bounded. Sessions use random opaque tokens; only token hashes are stored in SQLite. Cookies are HttpOnly and SameSite=Strict, expire after 12 hours, and become invalid after 30 idle minutes. State changes require an origin check, JSON content type, and the session’s CSRF token. Login attempts are limited per source/address and account identifier. These controls follow the [OWASP password guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), and [CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

The local database and new source files use owner-only file permissions; capture directories use mode 0700. API responses are not cached. Browser storage uses separate namespaces for each account and project. The first owner’s initial project imports older device drafts/outbox data once, without deleting the original database or overwriting newer records.

This is not encryption at rest. Anyone with access to the operating-system account/browser profile can inspect cached reports. Protect the device and backups. Offline views reflect previously granted access; server operations still require a current session and membership when connectivity returns. Signing out hides the workspace and removes remembered session context, while preserving scoped pending work for later recovery.

### Shared hosting

Localhost is the default. A non-loopback bind requires `CARRICK_PUBLIC_ORIGIN=https://your-host.example`. Provide an HTTPS reverse proxy that preserves the configured Host header; this setting does not create TLS. Cookies become Secure for an HTTPS origin. Keep SQLite, source files, model directories, credentials, and backups outside static hosting and Git. Provide managed backups, TLS termination, request limits, observability, and a durable worker queue before a wider deployment. The built-in synchronous HTTP server has not received a production security or load assessment.

## Retained submissions and capture failures

The browser writes submitted reports to IndexedDB before sending. The server records the original payload and its checksum before matching or model calls. Stable client IDs make retries idempotent. A successful response clears the browser outbox; a timeout, provider failure, or stale schedule leaves recoverable work.

Automatic report retries use increasing delays, with at most three failed attempts before manual action. **Retry** uses the saved source. **Use standard matching** explicitly creates a new request linked to the failed AI submission, preserving the original. Rules may produce less useful candidates and still require planner approval. Carrick does not silently present rules output as AI output.

Original scans and recordings are stored before OCR or speech inference. Failure responses include the retained capture ID. Users can download the original, retry processing, or transcribe manually. The capture panel also lists incomplete server receipts, allowing recovery if device storage was cleared. Submitted sources remain subject to normal storage/backup durability; disk failure, quota exhaustion, or deletion cannot be made lossless by retry logic.

Source states distinguish original text, machine output requiring review, and text confirmed by its submitter. OCR scores are engine scores, not calibrated accuracy probabilities. AI and rule proposals require a planner decision. A planner approval means a human accepted the proposed activity/date; it does not establish independent model accuracy. Source originals remain unchanged after transcription edits.

A newer schedule causes a pending report to require an explicit rebind and new request ID. It is then matched against the current version and reviewed again. Approvals remain attached to their original import; neither retries nor fallbacks bypass review.

## Schedule output

Exports provide an approved progress CSV and a validated JSON change set. An XER source can additionally produce a constrained updated XER. The writer targets existing imported TASK IDs and retains TASKPRED records, calendars, baseline/planned dates, and unrelated tables. It updates approved actual-start/finish fields, activity status, and remaining duration to zero on a completed activity when that column exists. Export output combines previously exported actuals with newly approved actuals on the same import version.

Validation checks approved identities, incompatible actuals, allowed field changes, supported parser reimport, unchanged relationships/counts/IDs, baseline fields, and resulting actual dates. Exports include source/output checksums and links to event/source/approval evidence. Unapproved proposals never enter schedule output. Imported files in storage remain unchanged.

Native output is withheld for CSV sources or completed activities with no actual start. Finish-only evidence remains in the JSON change set; no start date is invented. Unsupported XER structure/required columns fail validation. New day-precision actuals serialize at 00:00, while existing timestamps are retained. The parser and fixtures cover a limited schedule variant; broad version, calendar, encoding, resource, and multi-project interoperability has not been established.

`round_trip_verified` means Carrick’s parser accepted the generated output and internal checks passed. `oracle_import_verified` remains false. A planner must validate the file/change set in a controlled P6 project and inspect import settings and recalculated results before updating the master schedule. The writer does not replace P6 scheduling, resource calculations, or calendar logic. Fields were checked against the [Oracle XER mapping reference](https://docs.oracle.com/cd/G18294_01/English/Mapping_and_Schema/xer_import_export_data_map_project/xer_import_export_data_map_project.pdf).

## Implemented account and recovery routes

| Route | Purpose |
| --- | --- |
| `GET /api/auth/status` | Whether initial setup is required |
| `POST /api/auth/setup`, `/api/auth/login` | First owner creation or sign-in |
| `GET /api/auth/me`, `/api/projects` | Current account, CSRF token, memberships |
| `POST /api/auth/logout`, `/api/auth/password` | Sign out or change password |
| `POST /api/projects` | Create a project owned by the current account |
| `GET /api/members`, `POST /api/members` | Owner-managed project access |
| `GET /api/submissions`, `GET /api/submissions/{id}` | Incomplete receipts or retained payload |
| `POST /api/submissions/{id}/retry` | Retry a retained report; optional explicit analysis mode |
| `GET /api/captures/incomplete` | Captures whose processing needs recovery |
| `GET /api/captures/{id}`, `/api/captures/{id}/original` | Capture receipt or original bytes |
| `POST /api/captures/{id}/retry`, `/api/captures/{id}/manual` | Retry extraction or attach human transcription |
| `GET /api/exports/{id}.csv`, `.xer`, `.json` | Authorized output downloads |

Project requests send `X-Carrick-Project`. Writes also send `X-CSRF-Token`; both values come from authenticated membership/session responses. Ordinary capture/export download links derive their project from the resource and still require membership.

## Verification and remaining evidence

On 2026-10-02 the project environment passed 25 regression tests and 11 Chrome browser workflows. The standard Python environment passed 24 tests and skipped the optional PDF test; the project environment included its dependency and passed that test as well. See [verification commands and coverage](../../tests/README.md).

AI, OCR, and speech providers are deterministic test adapters. Browser microphone capture uses Chrome’s fake device. These tests verify integration, failures, authorization, data retention, and approval boundaries; they do not measure real recognition accuracy or service latency/cost. Independent P6 import, representative field-data evaluation, and activated calibrated routing thresholds remain outstanding.
