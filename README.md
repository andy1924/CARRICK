# Carrick

Carrick turns field progress reports into traceable proposals for updating an infrastructure project schedule. Supervisors can describe work in familiar language; planners retain control over uncertain matches and exported schedule changes.

This repository contains a runnable local prototype and the design documentation. It supports XER or CSV schedule import, typed notes, CSV logs, text/email/PDF reports, planner decisions, and an approved progress CSV export. An optional AI path retrieves activities from the imported schedule, extracts structured events, and reranks existing TASK IDs. It also includes scan OCR, local handwriting and speech adapters, browser microphone capture, saved offline reports, local Ollama RAG, and dependency-based schedule scenarios. These additions need the setup described below; they have not been tested in this session. Native schedule-file output remains planned work.

## Run locally

Requires Python 3.11 or newer. Basic text and CSV workflows need no package installation.

```bash
python3 -m services.api.app
```

Open `http://127.0.0.1:8765` for the interactive introduction, or go to `http://127.0.0.1:8765/app` for the workspace. The introduction previews matching against a synthetic schedule without saving notes. In the workspace, select **Load sample project**, capture a field update, review it, and create an export. The local SQLite database is stored under `data/private/` and ignored by Git. The server binds to localhost by default and has no production authentication; do not expose it publicly.

## Enable AI analysis

The ignored `.env` file is ready for your `OPENAI_API_KEY`. Set `CARRICK_AI_MODE=openai` and restart the server. The report composer then offers AI-assisted matching. This mode sends the note and retrieved schedule activity snippets to OpenAI; the key stays on the local server. The model proposes events and TASK IDs, while a planner confirms every actual date and activity before export. The rule-based mode remains available.

AI uses OpenAI embeddings for retrieval and a structured model response for extraction and reranking. To use a dedicated local cross-encoder for reranking instead, install the optional package and set `CARRICK_RERANKER=cross_encoder` in `.env`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-ai.txt
.venv/bin/python -m services.api.app
```

For legacy selectable-text PDF imports, install `requirements-documents.txt`. The reviewed document upload path, including scanned pages and diary photos, uses `requirements-capture.txt` plus locally installed Tesseract; handwriting additionally needs a local vision model. `.eml` and `.txt` imports need no extra package. See [AI architecture](docs/architecture/ai-rag.md) for safeguards and model setup.

Compare rule-based and AI results on the synthetic evaluation set after adding a key:

```bash
.venv/bin/python -m scripts.evaluate_matching --ai
```

The small synthetic set is a development check, not a claim of production accuracy.

Run the checks with:

```bash
python3 -m unittest discover -s tests -v
```

## Scans, voice, offline use, and forecasting

The workspace adds editable OCR page previews, microphone recording and transcript correction, device-local drafts and an outbox, and **Schedule insights** with duration scenarios, float, WBS summaries, dependency conflicts, and an illustrative P50/P80 envelope. Source scans and recordings stay linked to submitted reports.

See [capture and offline setup](docs/architecture/capture-offline-analytics.md) for package installation, local model provisioning, supported inputs, data storage, API contracts, and forecasting assumptions. `.env.example` includes the local model settings. After provisioning, start the local AI profile with `.venv/bin/python -m scripts.run_offline`. Standard matching and analytics do not require an LLM.

Restart the Python server after updating these files so new endpoints and database migrations load. No tests, browser automation, model downloads, or inference were run for these additions.

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
| `services/worker/` | Import, extraction, matching, AI retrieval, and document text ingestion |
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
