# Worker service

The current `engine.py` handles schedule parsing, rule-based event extraction, lexical candidate ranking, and routing. `ai.py` adds OpenAI-backed event extraction and semantic retrieval, with structured model or local cross-encoder reranking. `ingest.py` extracts text from uploaded messages and selectable-text PDFs. These modules are called synchronously by the local API; scanned PDFs still need OCR before import. Spreadsheet parsing runs in the API.

For a shared deployment, these operations should become retryable jobs keyed by source ID and processing version. Duplicate detection, richer warning checks, and native schedule export validation remain planned.

See [system architecture](../../docs/architecture/system.md).
