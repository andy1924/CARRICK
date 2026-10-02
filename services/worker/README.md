# Worker service

The current `engine.py` handles schedule parsing, rule-based event extraction, lexical candidate ranking, and routing. `ai.py` adds cloud or local Ollama event extraction and semantic retrieval, with structured model or local cross-encoder reranking. `capture.py` supplies local Tesseract OCR, vision transcription for diary scans, and faster-whisper speech transcription. `local_models.py` restricts local inference transport to loopback. `analytics.py` calculates read-only elapsed-day dependency scenarios, float, WBS summaries, and an illustrative risk envelope. `ingest.py` handles legacy text/email/PDF ingestion with OCR fallback. These modules run synchronously in the local API. Spreadsheet parsing runs in the API.

`duplicates.py` supplies conservative report identity and review-only similarity flags. `validation.py` checks actual conflicts, competing claims, and FS/SS/FF/SF graph constraints. `routing.py` loads explicitly activated policies tied to reviewed evidence, model configuration, code revision, and supported cohorts. `usage.py` and `quality.py` supply content-free accounting and evaluation statistics; `scripts/quality.py` exports independent-label templates, evaluates reviewed cases, and creates gated policy artifacts. No new production results or calibrated artifact are provided by these code additions.

For a shared deployment, these operations should become retryable jobs keyed by source ID and processing version. Native schedule export validation remains planned. See [reliability and calibration](../../docs/quality/reliability-and-calibration.md).

See [system architecture](../../docs/architecture/system.md).
