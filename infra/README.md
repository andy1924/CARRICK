# Infrastructure

Deployment configuration will go here after the first vertical slice works locally. The initial topology is a web client, API, worker, PostgreSQL database, durable job queue, and versioned file store. Keep credentials in environment variables or a secret manager, never in committed files.

See [system architecture](../docs/architecture/system.md).

The implemented workstation deployment can use local OCR, speech, generation, and embeddings without internet after provisioning. Start it with `python -m scripts.run_offline`; see [offline deployment and model preparation](../docs/architecture/capture-offline-analytics.md). Model files belong outside Git or under the ignored `models/` directory. This launcher does not install packages or download weights.
