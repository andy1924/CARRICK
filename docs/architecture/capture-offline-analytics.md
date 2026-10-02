# Capture, offline operation, and schedule scenarios

This implementation extends the existing report-to-review workflow. The imported schedule remains a versioned snapshot; OCR, speech, local AI, and forecasts do not approve actuals or rewrite baseline logic.

## Implemented paths

| Capability | Implementation | Required setup or boundary |
| --- | --- | --- |
| Printed scans and diary PDFs | Per-page PDF text extraction, falling back to local Tesseract OCR; PNG/JPEG/WebP uploads also supported | PyMuPDF, Tesseract, and installed language data |
| Handwritten diaries | Local Ollama vision transcription with editable page text | A provisioned image-capable model; transcription accuracy has not been measured |
| Voice capture | Browser microphone recording, playback, local faster-whisper transcription, and transcript correction | Secure browser context and a provisioned speech model |
| Server unavailable | Cached workspace shell, saved snapshot, typed drafts, attachment drafts, and a report outbox in IndexedDB | Visit the workspace while connected once; retain browser site data |
| Internet unavailable | Local Python API, SQLite, OCR, speech, and Ollama generation/embeddings continue on the workstation | Install packages, language data, and model files before disconnecting |
| Forecasting | Forward dependency propagation, backward float calculation, recorded forecast overlays, and duration scenarios | Imported dates and valid dependencies |
| Analytics | Critical activities, overdue work, WBS summaries, dependency conflicts, and an illustrative simulated risk envelope | Elapsed-day assumptions; this is not the P6 calendar engine |

The client can capture and retain work while its server is unavailable. OCR, transcription, AI matching, decisions, exports, and new scenario calculations require the local server. A cached scenario remains readable. This is a browser application using native microphone APIs, not a separate iOS or Android binary.

## Source and review flow

1. Upload a scan or record a voice note. Attachments are retained in browser storage until submission or explicit discard.
2. The local API extracts pages or transcribes speech, stores the original under `data/private/captures/`, and returns a capture receipt.
3. The user corrects extracted text before submitting a report. OCR confidence is a recognition diagnostic, not activity matching confidence. Handwriting has no confidence percentage.
4. The report references the capture receipt. Page numbers, extraction warnings, and original-file checksums remain available. Original extraction and corrected report text are stored separately.
5. Existing retrieval, event validation, planner review, and approved export rules apply. The review card links to the original source.

Uploads are limited to 10 MB and 20 pages. Voice notes are limited to two minutes. Tesseract handles printed text; it is not treated as a reliable handwriting engine. Image transcription can misread dates, names, and TASK IDs, so the user reviews its output before activity matching. See the [Tesseract FAQ](https://tesseract-ocr.github.io/tessdoc/FAQ.html).

## Local model deployment

Carrick talks only to a loopback Ollama endpoint for its local profile. The client uses Ollama's [structured generation endpoint](https://docs.ollama.com/api/generate) and [embedding endpoint](https://docs.ollama.com/api/embed). Local embeddings are indexed separately from OpenAI embeddings. Existing quote/date validation and TASK ID allowlists apply to both providers.

The local profile does not fall back to a cloud provider. It rejects cloud model names and remote-tagged model entries. Disable cloud features on the Ollama service itself with `OLLAMA_NO_CLOUD=1` or `disable_ollama_cloud: true`, then restart that service, as described in the [Ollama FAQ](https://docs.ollama.com/faq).

### Prepare while connected

Create or use the project's Python environment, then install the optional capture packages:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-documents.txt -r requirements-capture.txt
```

Install Tesseract and the languages used by the team. On macOS, Tesseract is available through Homebrew:

```bash
brew install tesseract tesseract-lang
```

Install Ollama and provision a local generation model, an embedding model, and optionally an image-capable model. Use their actual installed names in `.env`. Model files must already be present; Carrick does not pull them. Choose sizes suitable for the workstation's memory and confirm the image model supports scanned handwriting before relying on it.

Provision a converted speech model explicitly while connected. For example, the [faster-whisper project](https://github.com/SYSTRAN/faster-whisper) supports converted Whisper model directories:

```bash
.venv/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("Systran/faster-whisper-small", local_dir="models/whisper-small")'
```

Set these values in the ignored `.env`; keep any existing API key there:

```dotenv
CARRICK_AI_MODE=ollama
CARRICK_OLLAMA_URL=http://127.0.0.1:11434
CARRICK_LOCAL_MODEL=YOUR_INSTALLED_GENERATION_MODEL
CARRICK_LOCAL_EMBEDDING_MODEL=YOUR_INSTALLED_EMBEDDING_MODEL
CARRICK_VISION_MODEL=YOUR_INSTALLED_IMAGE_MODEL
CARRICK_WHISPER_MODEL_PATH=/absolute/path/to/models/whisper-small
CARRICK_OCR_LANG=eng
CARRICK_RERANKER=llm
```

Leave the vision value blank if handwriting transcription is not needed. For multilingual printed reports, use installed Tesseract languages such as `eng+hin+mar`. Voice supports language detection and English, Hindi, or Marathi selection; recognition quality still depends on the recording and selected model.

### Run without internet

Start the provisioned Ollama service with its cloud features disabled. For a standalone service process:

```bash
OLLAMA_NO_CLOUD=1 ollama serve
```

Then run Carrick's local-only launcher:

```bash
.venv/bin/python -m scripts.run_offline
```

The launcher forces the local AI profile, binds Carrick to localhost, and disables Hugging Face/Transformers network lookups. faster-whisper loads only a local directory with `local_files_only=True`. Optional cross-encoder reranking additionally needs `requirements-ai.txt` and a local `CARRICK_CROSS_ENCODER_MODEL` directory.

Open `/app` once while the server is available so the service worker can cache its shell. Offline microphone capture requires HTTPS or localhost and browser permission. Remote access over plain HTTP does not enable microphone recording or service workers. See [MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder) and [service workers](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers).

## Outbox and schedule identity

Submitted offline reports carry `client_request_id` and the schedule version visible at capture time. Successful retries return the original report receipt. The local API serializes report submissions and records the receipt in the same transaction as the events.

If a new schedule is imported before submission, the API returns HTTP 409. The report stays in the device queue. The user can download a copy, discard it, or explicitly submit it for matching against the current import. Matching against that import still requires planner approval.

Device drafts are not automatically submitted. OCR pages and speech transcripts wait for correction. Pending submitted reports retry when the server returns; validation failures require a manual retry. AI failures retain the report and never silently switch providers. Decisions and exports are unavailable while disconnected.

IndexedDB stores reports and attachment blobs in the browser profile. Clearing site data or changing devices removes access to unsynced work; each saved item provides a download action. Source captures stored by the API remain on its local disk. This implementation does not provide multi-device replication, user accounts, or cloud backup.

## Forecast model

The engine uses the existing activity IDs and imported `TASKPRED` links. It supports FS, SS, FF, and SF relationships with lag, checks cycles, and excludes activities without usable planned dates. Approved actuals are overlaid for the selected data date; recorded forecasts provide scenario bounds. Historical scenarios ignore actuals after their data date. Imported source records remain unchanged.

Forward propagation estimates activity starts and finishes. Unstarted work uses the planned duration; started work scales the remaining portion after elapsed days. Overdue unfinished work assumes at least one further day because a remaining-duration measurement is unavailable. A backward pass calculates float relative to the projected project finish. Zero-float unfinished activities are shown as critical in this scenario. The user can scale remaining durations and download the result as a scenario CSV; it is separate from the approved actuals export.

Two hundred seeded simulations vary unfinished durations using an illustrative triangular factor of 0.8 / 1.0 / 1.5. The P50/P80 finish dates and criticality frequency describe that assumed model. They are not calibrated forecasts or measured delivery probabilities. WBS summaries, overdue counts, recorded blockers, excluded activities, and out-of-sequence actuals are also returned.

The current engine uses elapsed days and converts lag hours using 24 hours per day. It does not interpret P6 calendars, holidays, resource leveling, constraints, remaining-duration fields, retained-logic settings, or earned-value cost data. Do not use its float or completion dates as a replacement for a P6 recalculation.

## Endpoints and records

| Endpoint | Result |
| --- | --- |
| `GET /api/capture/status` | Local OCR and speech configuration availability |
| `POST /api/documents/extract` | Capture receipt and page-level extracted text |
| `POST /api/voice/transcribe` | Capture receipt, editable text, and timed segments |
| `GET /api/captures/{id}` | Original extraction metadata and checksum |
| `GET /api/captures/{id}/original` | Original document or recording |
| `POST /api/reports` | Existing report matching; optional capture receipt, corrected text, version, and retry ID |
| `GET /api/analytics` | Default data-date scenario |
| `POST /api/analytics/scenario` | Scenario for `as_of` and `duration_factor` |

SQLite gains `capture_assets`, `report_requests`, and a nullable `reports.capture_asset_id`. Existing local databases migrate during startup. Browser storage is independent of SQLite. A server restart is required after these Python changes.

## Verification status

Implementation was added without running tests, browser automation, model inference, or dependency installation, at the user's request. Package installation, model provisioning, runtime behavior, transcription accuracy, and forecast calibration have not been verified in this session.
