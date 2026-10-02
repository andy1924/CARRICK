# Report reliability, history, and reviewed evaluation

## Implementation status

The local application now contains duplicate grouping, structured conflict checks, filtered history, content-free processing telemetry, independent-label export, evaluation, and routing-policy calibration tools. These changes were authored without running tests, evaluations, browser automation, inference, or database migrations. Restart the local Python server to load the new routes and additive schema migrations.

No new production accuracy or latency result is claimed. No reviewed dataset or validated policy was fabricated. Production deployment still needs authentication, operational hardening, representative capture evaluation, and measured concurrency behavior. The existing small synthetic benchmark is a development result for an earlier revision.

## Duplicate reports and repeated actuals

Report identity is a SHA-256 digest of ordered input rows with NFC Unicode normalization, collapsed whitespace, reference date, discipline, and location. Letter case, numbers, punctuation, negation, and dates remain part of identity: TASK codes and engineering units can differ by case. Case folding is used only for review-only similarity. Matching is scoped to the imported schedule version. If a reference date is absent, the submission day is used only for duplicate identity; it does not become an actual date.

An exact repeat creates a source receipt linked to the original report group. Its filename, submitted content, corrected input rows, scan or recording reference, and receipt time are retained. It shares the canonical events and their decisions. Model inference is skipped. A different analysis mode does not create another set of events for identical input. To analyze against a new schedule, submit against that new import.

Similar wording produces review suggestions only. The current heuristic requires matching date/discipline/location contexts, at least 0.8 token overlap, and at least 0.9 sequence similarity. It compares the last 200 canonical reports and skips sequence comparisons above 20,000 characters. These heuristic thresholds are not calibrated probabilities. A near match is never suppressed or automatically merged; changed dates, quantities, and negation can be consequential.

Approval and export also check repeated actuals. The same TASK ID, actual kind, and date already present in imported or approved/exported progress is consolidated with status `duplicate`. A different date for an existing actual is blocked. Export manifests contain unique newly approved actuals. If all actuals are repeats, the API returns `id: null`, no download, and a consolidation message.

Historical reports receive a group ID during migration. Their identity fingerprints and missing input context are not guessed or backfilled. Exact grouping therefore applies to newly submitted reports; approval/export guards apply to historical events too. No events are deleted by this migration.

## Conflict and dependency checks

Checks are stored as `{code, severity, message}` rather than relying solely on display strings. They are computed at analysis, after clarification, for a planner's selected activity/date, again within the decision transaction, and before export. Approved/exported actuals overlay the imported schedule for validation; they do not modify the imported baseline.

| Check | Behavior |
| --- | --- |
| Missing/invalid or future actual date; unknown TASK ID | Blocks approval |
| Actual finish before known actual start | Blocks approval |
| Different date for an existing actual of the same kind | Blocks approval and export |
| Identical already recorded actual | Consolidates; no second schedule update |
| Finish with no actual start | Requires an explanatory decision note |
| FS, SS, FF, SF predecessor/successor sequence and lag violations | Requires an explanatory decision note |
| Missing predecessor actual; unsupported dependency/lag; missing endpoint; graph cycle | Requires an explanatory decision note; completeness is uncertain |
| Hourly lag checked against date-only actuals | Raises a precision warning |
| Competing pending dates, reversed start/finish claims, or “not started” versus an actual claim | Requires comparison of the sources and a decision note |
| Progress/forecast on completed work, negation after recorded start, forecast finish before actual start, completion above 100 percent | Flags a progress-note conflict; recording requires a decision note |
| New import while analysis/refinement is running | Returns a schedule conflict; the source must be rebound explicitly |
| Decision against an older import | Blocks approval/recording; rejection remains available |

Dependency lags use elapsed hours divided by 24, not P6 working calendars. Global graph warnings apply conservatively to actual approval. Pending suggestions are advisory evidence and never authoritative dates. A note can acknowledge sequence uncertainty; it cannot override a conflicting actual or reversed chronology. User corrections and subsequent decisions are recorded in the audit trail.

Every actual still needs a planner decision, including a staged event and an event using a calibrated policy. Native P6 recalculation and direct XER rewriting remain outside this implementation.

## History

The history view queries the server in pages of 50 events and can filter by:

- Full report text or candidate/activity context.
- Exact activity ID, including selected activities and suggested candidates.
- Exact discipline, ignoring case.
- Review status, including pending and consolidated actuals.
- Inclusive event, source-received, or decision date range.
- Source kind: written text, document, voice, or CSV log.
- Filename substring, exact report ID, or capture ID.
- Report groups with repeated source submissions.

Sources within a group are evaluated together for source-kind/filename/received-date filtering: a filename from one submission cannot satisfy a date from a different submission. Original captures remain downloadable. History includes decision notes, actors, actions, and times. Grouping by report or activity is explicitly limited to the current page; result counts count events, not reports. Suggested activities are distinguished from selected activities in the underlying response.

Offline history applies these filters to the last saved workspace snapshot and labels that limitation. It cannot query newly received server records while disconnected. It does not permit decisions or exports without the API.

## Independently reviewed dataset

Keep customer reports, schedules, reviewer identities, predictions, and artifacts under ignored `data/private/`. Public samples are schema examples only. The export command opens the workspace database read-only and creates a new dataset directory; it neither migrates the database nor edits decisions.

```bash
python3 -m scripts.quality export-labels --output-dir data/private/review-round-01
```

The resulting `cases.jsonl` contains original input rows for new reports and `reviewed: false`, empty labels, empty project/split assignments, and an adjudication flag set to false. It excludes exact duplicate aliases and does not copy model suggestions or planner decisions into gold labels. Older reports lack saved rows/context and require reconstruction from the source before review, especially CSV and multi-page inputs. Exporting is not reviewing.

Two distinct reviewers should label each case independently, then reconcile disagreements. Their nonempty identifiers, `reviewed: true`, and `adjudicated: true` attest that this happened; software cannot verify a person's independence. Label all claims, including negated, forecast, ambiguous, unmatched, and multi-event reports. Gold quotes must be exact contiguous text; use distinct quotes for distinct claims. Preserve ordered input rows and their original reference dates, work areas, disciplines, and capture warnings.

Each case needs `case_id`, `source_group_id`, `project_id`, `split`, `schedule`, `report`, `source_kind`, `stratum`, and a `gold` array. Each gold claim needs `quote`, `kind`, `event_date` (ISO or empty), `acceptable_activity_ids`, and `requires_review`. An unmatched claim has no acceptable IDs and requires review; an ambiguous claim may have several acceptable IDs and also requires review. An empty gold array is valid for a report containing no progress claims.

Use at least 500 independent source groups in each of the calibration and holdout sets, with at least three separate projects per set. Entire projects and source groups stay in one split. The evaluator rejects duplicate case IDs, split leakage, relabeled copies of the same schedule, repeated input masquerading as different groups, unreviewed labels, invented IDs, and unsupported input sizes. Freeze the holdout before tuning. Repeatedly inspecting holdout results and changing thresholds invalidates that holdout; the CLI does not enforce organizational dataset governance.

The required input strata default to clean, colloquial, ambiguous, unmatched, OCR-noisy, negated, and multi-event. Include actual site terminology and supported disciplines and source channels. Synthetic text does not establish production performance. See the unreviewed schema example in `data/samples/reviewed-case-template.jsonl`.

## Evaluation

Commands are explicit tools; the application never invokes them automatically. AI evaluation makes model requests using the configured cloud or local provider. Rules evaluation makes no model requests.

```bash
python3 -m scripts.quality evaluate --cases data/private/review-round-01/cases.jsonl --mode rules --as-of 2026-10-02 --output data/private/rules-round-01.json
python3 -m scripts.quality evaluate --cases data/private/review-round-01/cases.jsonl --mode ai --as-of 2026-10-02 --rates data/private/model-rates.json --output data/private/ai-round-01.json
```

Use the same fixed `--as-of` date for comparisons. For local AI, replace `--rates` with an explicit `--local-hourly-cost` in USD. A zero local rate is an explicit accounting assumption, not proof of free infrastructure.

Evaluation reports include extraction precision/recall and counts, kind/date correctness, fully correct unambiguous claim accuracy, top-one/top-three matching, candidate retrieval recall, safe review routing recall, staging precision/coverage, report failures, p50/p95/p99 wall latency, raw content-free model-call latency/usage, token totals, and known/unknown cost. Missing or extra claims and failed reports count against coverage. Claim alignment uses normalized exact quotes; paraphrased extraction is not accepted silently. Slice results are included for source, discipline, and input stratum.

Schedule indexing is measured separately from report processing. Index cost/latency and checksums are retained in `cold_indexes`; report measurements use those already built vectors. The reported per-report cost and its release gate amortize relevant index costs over the evaluated reports; warm cost and index cost remain separately visible. Cross-encoder warmup can appear in the first report measurement. Hardware platform, Python version, model pipeline, code hash, schedule hashes, label-file hash, and date context accompany the result. This is a serial matching evaluation, not a concurrency/load benchmark. Imported schedule snapshots supply known actuals; it does not replay the history of every prior approved event.

Claim-level Wilson intervals and deterministic bootstrap intervals that resample entire source groups/projects are reported. Bootstrap intervals describe observed cohorts, not guaranteed performance on unseen projects. Minimum support gates prevent a tiny high-precision sample from being labeled calibrated.

Usage accounting records only provider, endpoint, model, latency, token counts, and failure flags. It does not log prompts, keys, transcripts, or generated content. Embedding token accounting follows the usage returned by the [official embeddings API](https://developers.openai.com/api/reference/resources/embeddings). A missing usage field remains unknown. Cloud cost uses caller-supplied model prices with `as_of` and `source`; use `data/samples/evaluation-rates.example.json` as a blank template, with USD prices per million tokens. Cached input requires its own rate when observed. Unknown prices/usage and failed unmetered calls do not become zero-cost successes. Local cost is explicit wall time multiplied by the supplied hourly rate.

These costs cover measured inference/compute assumptions. Capture processing, idle hardware, storage, networking, human review, and total hosting costs are not included. OCR character/word error rates, voice transcription in site noise, native external schedule import, and live concurrency require separate representative evaluation before a production claim.

## Threshold calibration and activation

```bash
python3 -m scripts.quality calibrate --predictions data/private/ai-round-01.json --target-precision 0.98 --min-coverage 0.10 --max-p95-ms 15000 --max-cost-usd 0.05 --output data/private/routing-round-01.json
```

The budget values above are example release targets, not measured costs or latency. Set targets appropriate to your deployment before examining holdout results. The calibration grid chooses score/margin thresholds using calibration cases only, optimizing coverage subject to a 95-percent Wilson lower bound and at least 100 staged actual proposals. Model ambiguity and structural warnings remain reasons for review regardless of score. Existing scores are ranking signals, not model-reported confidence probabilities; AI ordering is semantic while its stored numeric score remains a lexical/context signal.

Activation requires all of the following:

- At least 500 independently grouped reviewed reports and three projects in each split.
- At least 100 staged actuals on holdout, passing the precision lower bound and coverage target.
- Passing confidence bounds under both source-group and project bootstrap resampling on both splits.
- Holdout report failure rate at most one percent, p95 latency within budget, known cost and an explicit passing per-report cost budget.
- At least 50 holdout reports per observed source/discipline/stratum. Staging cohorts need at least 30 staged claims and target precision; review-only cohorts need 30 gold review claims and passing safe-review recall.
- Every required input stratum present on holdout.

Failed gates produce a `candidate` artifact, never an active validated policy. Outputs refuse to overwrite earlier files. Evaluation artifacts must match the current implementation before calibration. To activate a passing artifact, set `CARRICK_ROUTING_POLICY` to its absolute path in the ignored `.env` and restart the server. Policies are bound to the generation/embedding/reranker pipeline and implementation hash. Source channels or disciplines outside the reviewed cohort fall back to the uncalibrated baseline. Score/margin thresholds are not permission to approve an actual.

Absent, incompatible, stale, or unvalidated policies retain the explicitly uncalibrated baseline of score 0.38 and margin 0.12. Uncalibrated AI events stay in `needs_review`. No validated artifact is supplied with this change because no independently reviewed production dataset was provided and evaluation was not run.

## Operational measurements

`GET /api/quality/status` and **Progress history → Processing and routing evidence** expose the last 1,000 processing attempts, errors, report/queue/model latency quantiles, observed token counts, unknown-usage calls, duplicate group counts, and current policy metadata. Clarification requests are distinguished from report analysis. The window spans imports; it is not a per-project production accuracy result. Cold indexing can be included in live report latency when a cache is absent.

This endpoint deliberately leaves accuracy and cost unknown. Planner acceptance is not independent ground truth; operational telemetry is not a substitute for the reviewed evaluation. Capture previews/transcription are outside this telemetry window. Telemetry write failure cannot change a committed report into a failed submission receipt.
