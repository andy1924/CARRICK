"""Operational telemetry is distinct from reviewed accuracy evidence."""
import json
from services.worker.quality import quantiles
from services.api.auth import project_context
from services.worker.routing import pipeline_for, policy_for
from services.worker.ai import ai_status, model_client, load_local_env


def quality_status(db):
    load_local_env()
    ai = ai_status()
    client = model_client() if ai["available"] else None
    pipelines = [pipeline_for(), pipeline_for(client,ai["reranker"])] if client else [pipeline_for()]
    rows = [dict(row) for row in db.execute("SELECT * FROM processing_runs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1000",(project_context.get() or "prj_default",))]
    calls = [call for row in rows for call in json.loads(row["model_calls"])]
    tokens = lambda key: sum(call.get(key) or 0 for call in calls)
    return {"scope": "Latest 1,000 processing attempts across schedule imports; report analysis and clarification, excluding OCR and transcription",
            "attempts": len(rows), "failed_attempts": sum(row["failed"] for row in rows),
            "report_latency_ms": quantiles([row["elapsed_ms"] for row in rows if row["mode"] != "clarification"]),
            "queue_latency_ms": quantiles([row["queue_ms"] for row in rows]),
            "model_latency_ms": quantiles([call["latency_ms"] for call in calls]),
            "model_calls": len(calls), "observed_input_tokens": tokens("input_tokens"), "observed_output_tokens": tokens("output_tokens"),
            "calls_with_unknown_usage": sum(call.get("input_tokens") is None or call.get("output_tokens") is None for call in calls),
            "cost_usd": None, "cost_note": "Supply dated model prices to the offline evaluation command; unknown cost is not zero",
            "duplicate_submissions": db.execute("SELECT count(*) FROM reports r JOIN schedule_versions v ON v.id=r.version_id WHERE r.duplicate_of IS NOT NULL AND v.project_id=?",(project_context.get() or "prj_default",)).fetchone()[0],
            "duplicate_groups": db.execute("SELECT count(*) FROM (SELECT r.duplicate_group_id FROM reports r JOIN schedule_versions v ON v.id=r.version_id WHERE v.project_id=? GROUP BY r.duplicate_group_id HAVING count(*)>1)",(project_context.get() or "prj_default",)).fetchone()[0],
            "routing_policies": [policy_for(pipeline) for pipeline in dict.fromkeys(pipelines)],
            "accuracy": None, "accuracy_note": "Operational decisions are not independently reviewed ground truth. Use scripts.quality to evaluate reviewed cases."}
