# System architecture

## Shape

The local prototype uses a static web client, a Python standard-library HTTP service, synchronous processing, and SQLite. It supports the first report-to-export loop without installation. The deployment target below separates heavy processing into a worker and uses a shared relational database. Keep the schedule adapter and matching engine behind interfaces. Add infrastructure when workload measurements justify it.

```mermaid
flowchart LR
    S[Supervisor interface] --> A[API]
    P[Planner interface] --> A
    A --> DB[(Application database)]
    A --> Q[Job queue]
    Q --> W[Worker]
    W --> I[Schedule and report adapters]
    W --> X[Event extraction]
    W --> M[Candidate retrieval and ranking]
    W --> V[Rule checks]
    I --> F[(Versioned file store)]
    X --> DB
    M --> DB
    V --> DB
    A --> E[Approved export builder]
    E --> F
    E --> DB
```

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| Web client | Text capture, spreadsheet upload, clarification, review queue, activity history, export summary |
| API | Authentication, access checks, request validation, job creation, decisions, transactional state changes |
| Worker | Format parsing, text extraction, matching, duplicate detection, export validation |
| Database | Schedule snapshots, source records, extracted events, candidates, proposals, decisions, audit trail |
| File store | Original uploads, versioned schedule imports, and generated exports with checksums |
| Schedule adapter | Convert supported schedule formats into a common activity graph and generate validated outputs |

## Ingestion flow

```mermaid
sequenceDiagram
    participant U as Reporter
    participant API
    participant W as Worker
    participant DB
    participant P as Planner
    U->>API: Submit text or spreadsheet
    API->>DB: Save source and create job
    API-->>U: Job receipt
    API->>W: Process job
    W->>DB: Save extracted events and candidate matches
    W->>DB: Save proposals or review items
    API-->>U: Clarification when useful
    P->>API: Review uncertain items
    API->>DB: Save decision and audit event
```

## Matching pipeline

1. Normalize activity names, WBS paths, codes, locations, disciplines, and report terminology without discarding original strings.
2. Generate candidates using exact identifiers, lexical search, and semantic retrieval where available. A missing semantic service must not prevent a safe review path.
3. Rank candidates with report context and schedule context. Test a cross-encoder against simpler baselines before making it a production dependency.
4. Use relationship state, planned dates, and location as ranking features and warnings. Do not silently prune every out-of-sequence activity.
5. Route clear candidates to a staged proposal, close candidates to clarification, and uncertain or contradictory candidates to planner review. Thresholds come from held-out evaluation data.

## Data and job boundaries

- A source report is stored before any model processing so retries are idempotent and evidence remains available.
- Each extracted event and proposal has a stable ID. Reprocessing creates a new processing run, not a silent replacement.
- Worker jobs can retry safely using a source ID and processing version.
- Decisions and export manifests are committed transactionally. A failed export does not mark proposals exported.
- Long-running parsing and model work runs in a separate worker process; the API returns a job receipt and exposes status.

## Current and later technology direction

- **Current:** plain JavaScript web client, Python standard-library API, synchronous engine, and SQLite. The app binds to localhost and has no production authentication.
- **Later:** a typed API, separate job worker, PostgreSQL, durable queue, and versioned file storage. Evaluate semantic retrieval and a cross-encoder only against the matching benchmark.
- Heavy parsing or inference should not rely on in-process API background tasks in a shared deployment.

See [data model](data-model.md), [API outline](api.md), and [schedule integration](schedule-integration.md) for the contracts behind these boundaries.
