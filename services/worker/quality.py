"""Reviewed-label evaluation utilities; metrics never infer human ground truth."""
import math
import random
from collections import defaultdict


def ratio(numerator, denominator):
    return round(numerator / denominator, 5) if denominator else None


def wilson(correct, total):
    if not total: return {"lower": None, "upper": None}
    z, p = 1.959964, correct / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z/total)
    return {"lower": round(max(0, center-half), 5), "upper": round(min(1, center+half), 5)}


def quantiles(values):
    values = sorted(values)
    def percentile(p):
        if not values: return None
        position = (len(values)-1)*p
        low = int(position); high = min(low+1, len(values)-1)
        return round(values[low] + (values[high]-values[low])*(position-low), 2)
    return {"samples": len(values), "p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99)}


def staged(claim, score, margin):
    return bool(claim["eligible"] and claim["score"] >= score and claim["margin"] >= margin)


def cluster_precision(rows, score, margin, key="source_group_id", draws=500):
    """Resample whole source/project groups, preserving correlated event claims."""
    groups = defaultdict(list)
    for row in rows: groups[row[key]].extend(row["claims"])
    counts = []
    for claims in groups.values():
        proposals = [c for c in claims if staged(c,score,margin)]
        counts.append((sum(c["correct"] for c in proposals),len(proposals)))
    if not counts or not sum(total for _,total in counts): return {"lower":None,"upper":None,"groups":len(counts),"draws":draws}
    rng, values = random.Random(20617), []
    for _ in range(draws):
        sample = [rng.choice(counts) for _ in counts]
        total = sum(n for _,n in sample)
        values.append(sum(n for n,_ in sample)/total if total else 0)
    values.sort()
    return {"lower":round(values[int(.025*(draws-1))],5),"upper":round(values[int(.975*(draws-1))],5),"groups":len(counts),"draws":draws}


def summarize(rows, score=.38, margin=.12):
    claims = [claim for row in rows for claim in row["claims"]]
    gold = sum(row["gold_count"] for row in rows)
    extracted = sum(row["predicted_count"] for row in rows)
    aligned = sum(claim["aligned"] for claim in claims)
    linked = [claim for claim in claims if claim.get("matchable")]
    fast = [claim for claim in claims if staged(claim, score, margin)]
    correct = sum(claim["correct"] for claim in fast)
    costs = [row["cost_usd"] for row in rows if row["cost_usd"] is not None]
    calls = [call for row in rows for call in row["model_calls"]]
    return {"reports": len(rows), "gold_events": gold, "predicted_events": extracted,
            "extraction_precision": ratio(aligned, extracted), "extraction_recall": ratio(aligned, gold),
            "event_kind_accuracy": ratio(sum(c["kind_correct"] for c in claims), gold),
            "event_date_accuracy": ratio(sum(c["date_correct"] for c in claims), gold),
            "full_event_accuracy": ratio(sum(c["correct"] for c in claims), gold),
            "activity_top1": ratio(sum(c["top1"] for c in linked), sum(r["matchable_gold"] for r in rows)),
            "activity_top3": ratio(sum(c["top3"] for c in linked), sum(r["matchable_gold"] for r in rows)),
            "retrieval_recall": ratio(sum(c["retrieved"] for c in linked), sum(r["matchable_gold"] for r in rows)),
            "safe_review_recall": ratio(sum(not staged(c,score,margin) for c in claims if c.get("requires_review")), sum(r["review_gold"] for r in rows)),
            "staged_actuals": len(fast), "staging_precision": ratio(correct, len(fast)),
            "staging_precision_95ci": wilson(correct, len(fast)), "staging_coverage": ratio(len(fast), gold),
            "failed_reports": sum(bool(r["error_type"]) for r in rows), "error_rate": ratio(sum(bool(r["error_type"]) for r in rows), len(rows)),
            "report_latency_ms": quantiles([r["latency_ms"] for r in rows]),
            "model_calls":len(calls), "observed_input_tokens":sum(c.get("input_tokens") or 0 for c in calls),
            "observed_output_tokens":sum(c.get("output_tokens") or 0 for c in calls),
            "calls_with_unknown_usage":sum(c.get("input_tokens") is None or c.get("output_tokens") is None for c in calls),
            "known_cost_reports": len(costs), "unknown_cost_reports": len(rows)-len(costs),
            "known_cost_subtotal_usd": round(sum(costs), 6),
            "total_cost_usd": round(sum(costs), 6) if len(costs) == len(rows) else None,
            "cost_per_report_usd": ratio(sum(costs),len(rows)) if len(costs)==len(rows) else None}
