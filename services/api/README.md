# API service

The current service is a Python standard-library HTTP server with SQLite persistence. It supports schedule import, report submission, event listing, planner decisions, and approved CSV export. It is for local evaluation only and binds to localhost by default.

Authentication, authorization, idempotent mutation keys, and asynchronous jobs are required before a shared deployment. Heavy parsing and model inference belong in a separate worker in that later architecture.

See [API outline](../../docs/architecture/api.md) and [data model](../../docs/architecture/data-model.md).
