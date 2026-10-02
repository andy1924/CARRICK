"""Load only explicitly activated, held-out-validated routing policies."""

import json
import math
import os
import hashlib
from pathlib import Path


BASELINE = {"policy_id": "uncalibrated-baseline", "pipeline_id": "rules-lexical-v1", "min_score": .38, "min_margin": .12, "calibrated": False}


def policy_for(pipeline_id="rules-lexical-v1"):
    path = os.environ.get("CARRICK_ROUTING_POLICY", "")
    if not path:
        return {**BASELINE, "pipeline_id": pipeline_id}
    try:
        artifact = json.loads(Path(path).read_text())
        if (artifact.get("schema_version") != 1 or artifact.get("pipeline_id") != pipeline_id or
            artifact.get("status") != "validated" or not artifact.get("holdout_passed") or
            artifact.get("calibration_cases", 0) < 500 or artifact.get("holdout_cases", 0) < 500 or
            not artifact.get("dataset_sha256") or not artifact.get("policy_id") or
            artifact.get("implementation_sha256") != implementation_hash()):
            raise ValueError("Policy does not meet the reviewed dataset requirements")
        score, margin = float(artifact["min_score"]), float(artifact["min_margin"])
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in (score, margin)):
            raise ValueError("Invalid thresholds")
        return {**artifact, "calibrated": True}
    except (OSError, ValueError, TypeError, KeyError):
        return {**BASELINE, "pipeline_id": pipeline_id, "message": "Configured policy is incompatible or unvalidated; conservative baseline is active"}


def implementation_hash():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ("engine.py", "ai.py", "validation.py", "routing.py", "quality.py", "duplicates.py", "usage.py", "local_models.py"):
        digest.update(name.encode()); digest.update((root/name).read_bytes())
    digest.update((root.parents[0]/"api"/"app.py").read_bytes())
    digest.update((root.parents[1]/"scripts"/"quality.py").read_bytes())
    return digest.hexdigest()


def pipeline_for(client=None, reranker="llm"):
    if client is None:
        return "rules-lexical-v1"
    return f"rag-v1:{client.model}:{client.embedding_model}:{reranker}:" + (os.environ.get("CARRICK_CROSS_ENCODER_MODEL", "default") if reranker == "cross_encoder" else "structured")


def routing_details(candidates, pipeline_id="rules-lexical-v1", source_kind=None, discipline=None):
    policy = policy_for(pipeline_id)
    if policy["calibrated"] and ((source_kind is not None and source_kind not in policy.get("validated_sources",[])) or
            (discipline is not None and (discipline or "unspecified").casefold() not in policy.get("validated_disciplines",[]))):
        policy = {**BASELINE,"pipeline_id":pipeline_id,"message":"This source or discipline was outside the reviewed cohort"}
    top = candidates[0]["score"] if candidates else 0
    margin = top - candidates[1]["score"] if len(candidates) > 1 else top
    return {"policy_id": policy["policy_id"], "pipeline_id": pipeline_id, "calibrated": policy["calibrated"],
            "score": top, "margin": round(margin, 3), "min_score": policy["min_score"], "min_margin": policy["min_margin"]}
