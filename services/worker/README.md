# Worker service

The current `engine.py` handles schedule parsing, event extraction, lexical candidate ranking, and routing. It is called synchronously by the local API. Spreadsheet parsing runs in the API.

For a shared deployment, these operations should become retryable jobs keyed by source ID and processing version. Duplicate detection, richer warning checks, and native schedule export validation remain planned.

See [system architecture](../../docs/architecture/system.md).
