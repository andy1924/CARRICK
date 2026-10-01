# Carrick

Carrick turns field progress reports into traceable proposals for updating an infrastructure project schedule. Supervisors can describe work in familiar language; planners retain control over uncertain matches and exported schedule changes.

This repository contains a runnable local prototype and the design documentation. The first working slice supports XER or CSV schedule import, text and CSV field reports, event extraction, candidate ranking, planner decisions, and an approved progress CSV export. Matching currently uses transparent rules and lexical similarity; advanced models and native schedule-file output remain planned work.

## Run locally

Requires Python 3.11 or newer. No package installation is needed.

```bash
python3 -m services.api.app
```

Open `http://127.0.0.1:8765` for the interactive introduction, or go to `http://127.0.0.1:8765/app` for the workspace. The introduction previews matching against a synthetic schedule without saving notes. In the workspace, select **Load sample project**, capture a field update, review it, and create an export. The local SQLite database is stored under `data/private/` and ignored by Git. The server binds to localhost by default and has no production authentication; do not expose it publicly.

Run the checks with:

```bash
python3 -m unittest discover -s tests -v
```

## Intended product loop

1. Import a versioned schedule and index its activities, WBS, locations, and relationships.
2. Accept a text report or discipline spreadsheet and extract activity-level progress events.
3. Suggest schedule activity matches, using schedule context to improve ranking.
4. Clarify ambiguous reports or send them to planner review.
5. Stage validated actuals, preserve the source evidence, and export approved progress records.
6. Retain a structured progress history for later analysis.

## Repository map

| Path | Responsibility |
| --- | --- |
| `apps/web/` | Supervisor capture and planner review interface |
| `services/api/` | HTTP API, orchestration, authorization, and transactional writes |
| `services/worker/` | Import, extraction, matching, and export jobs |
| `packages/contracts/` | Shared request, event, and export contracts |
| `data/samples/` | Public, synthetic fixtures only |
| `infra/` | Local and deployment configuration |
| `tests/` | Contract, integration, and evaluation suites |
| `docs/` | Product, architecture, research, and decision records |

Start with the [documentation index](docs/README.md), then read the [product scope](docs/product/requirements.md), [system architecture](docs/architecture/system.md), and [brand guide](docs/brand.md).

## Repository rules

- Keep source reports, customer schedules, credentials, and local research PDFs outside the repository.
- Commit only synthetic or explicitly cleared sample data.
- Treat matching output as a proposal. The system of record changes only through a validated, auditable schedule export or an approved integration.
- Do not claim a matching accuracy, confidence probability, or format compatibility until it is measured.
