# API service

Python HTTP server with SQLite persistence, cookie sessions, per-project access, durable report receipts, captures, planner decisions, and CSV/XER/change-set exports. It binds to localhost by default. All project data and downloads require membership; imports, decisions, and exports require planner/owner access. Server-authenticated identity is recorded in decision and clarification audits.

Report requests accept idempotent client IDs. Sources are retained before inference; retries and standard-matching fallback preserve evidence. Exact repeats retain grouped source receipts. Decision/export validation runs inside SQLite write transactions. Heavy inference remains synchronous; a shared deployment should move it into durable worker jobs and provide an HTTPS reverse proxy, operational monitoring, and backups.

See [access and recovery](../../docs/architecture/access-output-recovery.md), [API outline](../../docs/architecture/api.md), and [verification suites](../../tests/README.md).
