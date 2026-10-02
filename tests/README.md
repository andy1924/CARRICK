# Verification suites

## Regression and authorization

```bash
python3 -m unittest discover -s tests -v
```

Use `.venv/bin/python` if optional document dependencies are installed there. The PDF text-layer test skips when `pypdf` is absent; installing `requirements-documents.txt` enables it. Other tests use the standard library.

The suites cover warning messages, source grounding, all dependency endpoint types, outgoing conflicts, graph cycles, durable failures, duplicate actual consolidation, planner approval/export boundaries, XER field preservation and parser round trip, login/CSRF/origin protection, project isolation, resource ID isolation, session logout, and access revocation.

Fixtures use temporary SQLite databases. AI tests mock `model_client`, not one provider implementation, and block external inference transport. They never use the developer key or customer schedule/report data.

## Browser workflows

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

Alternatively set `CARRICK_CHROME_PATH` to an installed Chrome executable. `CARRICK_TEST_PYTHON` selects the test server Python interpreter; `CARRICK_TEST_PORT` changes the default port 8766. See the [Playwright server configuration](https://playwright.dev/docs/test-webserver).

The runner starts `scripts.e2e_server` with temporary data and deterministic provider adapters. It refuses to reuse an existing server. Use the test entry point only for testing; it is not a production provider configuration. The application's real authentication and authorization stay enabled. Screenshots/traces for failures are stored in ignored `output/browser-tests/`.

Covered workflows:

1. Dashboard initialization and schedule import, with no JavaScript runtime errors.
2. Text report, planner review/approval, CSV/XER export, and XER reimport.
3. Scan preview/editing, native browser recording, transcript review, and approved export.
4. Offline submission, cached reload, and outbox synchronization after recovery.
5. Unavailable AI, retained source, and explicit standard-matching fallback.
6. Unavailable OCR, original retention, and human transcription.
7. Server report recovery after the device outbox is cleared.
8. Explicit rebind after a newer schedule import.
9. Server scan recovery after device drafts are cleared.
10. Legacy device draft migration without deleting originals or restoring discarded drafts twice.
11. Supervisor restrictions and inaccessible projects.

AI/OCR/speech adapters are mocked and microphone input comes from Chrome's fake device. Engines need their own representative-data evaluation. The browser suite does not make calls to OpenAI/Ollama or install/download local inference models.

## Latest run

2026-10-02: 25 regression tests passed using the project virtual environment; 11 Chrome browser workflows passed. No Oracle P6 installation was available for independent import acceptance. See [evaluation plan](../docs/quality/evaluation.md) for production accuracy, coverage, latency, cost, and calibration gates.
