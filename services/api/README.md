# API service

The current service is a Python standard-library HTTP server with SQLite persistence. It supports schedule import, report submission, event listing, planner decisions, and approved CSV export. It is for local evaluation only and binds to localhost by default.

Authentication, authorization, idempotent mutation keys, and asynchronous jobs are required before a shared deployment. Heavy parsing and model inference belong in a separate worker in that later architecture.

Report submissions already accept an idempotent client request ID. New exact repeats retain source receipts in one report group, while actual approval and export consolidate repeated schedule values. `history.py` provides parameterized filtering, pagination, grouped sources and audit history; `quality.py` exposes recent operational measurements separately from reviewed accuracy. Decision/export validation runs inside SQLite write transactions. Restart the API to load the additive report/event columns and indexes. These additions were not tested or evaluated in this session.

See [API outline](../../docs/architecture/api.md) and [data model](../../docs/architecture/data-model.md).
