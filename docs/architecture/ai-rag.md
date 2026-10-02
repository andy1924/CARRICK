# Grounded AI matching

Carrick's optional AI path retrieves records from the currently imported schedule. The retrieval corpus contains only its existing TASK IDs, activity names, WBS paths, locations, dates, and TASKPRED relationships. No generated activity becomes a schedule record.

## Current request path

1. Import the XER or CSV schedule. XER TASKPRED internal references are resolved to the displayed TASK IDs.
2. On first AI use, embed activity cards with `text-embedding-3-small` and cache the vectors by schedule version and embedding model in SQLite.
3. Embed the report, retrieve dense candidates, and add strong literal TASK ID and activity-name matches to the context. The retrieved cards are supplied to the language model.
4. Ask the configured OpenAI model for structured event claims. A claim's quote must occur in the submitted report. Dates and future/negated claims receive deterministic safeguards.
5. Retrieve again for each event, then rerank candidate TASK IDs. The default reranker uses a structured model response. `CARRICK_RERANKER=cross_encoder` switches to a local Sentence Transformers cross-encoder after installing the optional dependency.
6. Add relationship and missing-date warnings. Every AI result enters the planner queue. A supervisor can answer one clarification question to rerank the same existing activities; the answer and resulting IDs enter the audit trail.
7. A planner checks the source quote, activity, and date. Only an approved actual can enter the CSV export. The imported schedule is never modified by model output.

The current local API runs this synchronously. A deployed version should move indexing and inference to bounded worker jobs and add authentication, request budgets, rate limits, and project-level access controls.

## Trust boundaries

- The browser sends the key to no endpoint. The server reads `OPENAI_API_KEY` from the ignored `.env` file or process environment. API responses never include it.
- AI mode sends the field note and retrieved schedule snippets to OpenAI. The UI identifies this mode before submission. The Responses request uses `store: false`; project data handling should still be reviewed before use with private schedules.
- Source reports and retrieved records are treated as data, not instructions. Structured responses are validated against source quotes and the imported TASK ID set.
- Retrieval and reranker scores are ranking signals, not correctness probabilities. They are not shown as calibrated confidence.
- A model failure returns an explicit error. It does not silently relabel a rule-based result as an AI result.
- Reviewed document import now supports printed scan OCR and optional local vision transcription for handwritten diaries. See [capture, local inference, and offline deployment](capture-offline-analytics.md).

## Evaluation gate

Run `python3 -m scripts.evaluate_matching` for the rule baseline, then `python3 -m scripts.evaluate_matching --ai` with a configured key. The bundled synthetic examples exercise colloquial terms, repeated locations, tense, and missing direct word matches. Track top-one match, top-three recall, event-kind accuracy, latency, and cost. The examples are too small to establish an accuracy claim; a reviewed, held-out dataset is required before asserting the AI path outperforms the baseline.

The retrieval and reranking shape follows the [Sentence Transformers retrieve-and-rerank guide](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html). Structured model output and embeddings follow [OpenAI's structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs) and [embedding guide](https://developers.openai.com/api/docs/guides/embeddings).
