# Worker service

The current `engine.py` handles schedule parsing, rule-based event extraction, lexical candidate ranking, and routing. `ai.py` adds cloud or local Ollama event extraction and semantic retrieval, with structured model or local cross-encoder reranking. `capture.py` supplies local Tesseract OCR, vision transcription for diary scans, and faster-whisper speech transcription. `local_models.py` restricts local inference transport to loopback. `analytics.py` calculates read-only elapsed-day dependency scenarios, float, WBS summaries, and an illustrative risk envelope. `ingest.py` handles legacy text/email/PDF ingestion with OCR fallback. These modules run synchronously in the local API. Spreadsheet parsing runs in the API.

For a shared deployment, these operations should become retryable jobs keyed by source ID and processing version. Duplicate detection, richer warning checks, and native schedule export validation remain planned.

See [system architecture](../../docs/architecture/system.md).
