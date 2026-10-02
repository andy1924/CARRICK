"""Export independent label templates, evaluate, and calibrate reviewed reports.

Run explicitly with python3 -m scripts.quality; never called by the web app.
"""
import argparse
import hashlib
import json
import math
import platform
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from services.worker.ai import VALID_KINDS, activity_card, ai_status, analyze_report, load_local_env, model_client
from services.worker.duplicates import normalize
from services.worker.engine import extract_events, parse_schedule, rank_activities, route_event
from services.worker.quality import summarize, cluster_precision
from services.worker.routing import pipeline_for, routing_details, implementation_hash
from services.worker.usage import estimate_cost
from services.worker.validation import actual_checks


def write_new(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as file: json.dump(data, file, indent=2, ensure_ascii=False)


def export_labels(args):
    from services.api.app import DB_PATH
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "schedules").mkdir()
    # Read-only URI: exporting labels cannot migrate or change a live workspace.
    with sqlite3.connect(DB_PATH.resolve().as_uri()+"?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        versions = {row["id"]: dict(row) for row in db.execute("SELECT * FROM schedule_versions")}
        for version in versions.values():
            (destination / "schedules" / (version["id"]+"."+version["format"])).write_text(version["content"])
        with (destination / "cases.jsonl").open("x") as output:
            for report in db.execute("SELECT * FROM reports WHERE duplicate_of IS NULL ORDER BY created_at,id"):
                context = json.loads(report["identity_context"] or "[]")
                context = context[0] if len(context)==1 else {}
                rows = json.loads(report["input_rows"] or "null")
                case = {"case_id": report["id"], "source_group_id": report["duplicate_group_id"],
                        "project_id": "", "split": "", "reviewed": False, "reviewed_by": [], "adjudicated": False,
                        "schedule": "schedules/"+report["version_id"]+"."+versions[report["version_id"]]["format"],
                        "report": "\n\n".join(row["text"] for row in rows) if rows else report["content"], "rows": rows,
                        "report_date": context.get("date", ""),
                        "discipline": context.get("discipline", ""), "location": context.get("location", ""),
                        "source_kind": report["source_kind"], "stratum": "unclassified", "gold": [],
                        "review_context": "Verify original dates, input format and page/row context. Legacy reports need reconstructed input rows. Label independently without consulting model suggestions or planner decisions."}
                output.write(json.dumps(case, ensure_ascii=False)+"\n")
    print("Unreviewed templates saved to " + str(destination))


def reviewed_cases(path):
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not cases: raise ValueError("Dataset is empty")
    seen, groups, projects, identities = set(), {}, {}, {}
    for case in cases:
        case_id = case["case_id"]
        if case_id in seen: raise ValueError("Repeated case ID")
        seen.add(case_id)
        if case.get("split") not in {"calibration", "holdout"}: raise ValueError("Assign a calibration or holdout split")
        if not case.get("source_group_id") or not case.get("project_id"): raise ValueError("Source group and project IDs are required")
        reviewers = case.get("reviewed_by", [])
        if case.get("reviewed") is not True or case.get("adjudicated") is not True or len({r.strip() for r in reviewers if isinstance(r,str) and r.strip()}) < 2:
            raise ValueError("Each case needs two independent reviewers and adjudicated ground truth")
        for mapping, key in [(groups, case["source_group_id"]), (projects, case["project_id"])]:
            if key in mapping and mapping[key] != case["split"]: raise ValueError("Project or source leakage between splits")
            mapping[key] = case["split"]
        if case.get("source_kind") not in {"text", "spreadsheet", "document", "voice"}: raise ValueError("Label the source kind")
        if not case.get("stratum") or case["stratum"] == "unclassified": raise ValueError("Label the input stratum")
        if case.get("report_date"): date.fromisoformat(case["report_date"])
        if case.get("rows"):
            if "\n\n".join(row["text"] for row in case["rows"]) != case["report"]: raise ValueError("Report must preserve the ordered input rows")
            for row in case["rows"]:
                if row.get("event_date"): date.fromisoformat(row["event_date"])
        identity = (normalize(case["report"]),case.get("report_date",""),normalize(case.get("discipline","")),normalize(case.get("location","")))
        if identity in identities and identities[identity] != case["source_group_id"]:
            raise ValueError("Repeated input must use one source group, including across projects and splits")
        identities[identity] = case["source_group_id"]
        quotes = set()
        for gold in case["gold"]:
            if not gold.get("quote") or gold["quote"] not in case["report"]: raise ValueError("Gold quotes must occur verbatim in the supplied report")
            key = normalize(gold["quote"])
            if key in quotes: raise ValueError("Gold quotes must distinguish separate claims")
            quotes.add(key)
            if gold["kind"] not in VALID_KINDS: raise ValueError("Unknown gold event kind")
            if gold.get("event_date"): date.fromisoformat(gold["event_date"])
            if not isinstance(gold.get("acceptable_activity_ids"), list): raise ValueError("Provide acceptable imported activity IDs or an empty list")
            if not isinstance(gold.get("requires_review"), bool): raise ValueError("Label ambiguity or review requirement")
            if len(gold["acceptable_activity_ids"]) != 1 and not gold["requires_review"]: raise ValueError("Ambiguous and unmatched claims must require review")
    return cases


def evaluate(args):
    load_local_env()
    cases = reviewed_cases(args.cases)
    if args.output.exists(): raise ValueError("Choose a new evaluation output path")
    schedules, schedule_projects = {}, {}
    for case in cases:
        path = (args.cases.resolve().parent / case["schedule"]).resolve()
        if not path.is_relative_to(args.cases.resolve().parent): raise ValueError("Schedules must be inside the dataset directory")
        if str(path) not in schedules:
            text = path.read_text(); activities, relationships, _ = parse_schedule(text, path.name)
            schedules[str(path)] = {"activities": activities, "relationships": relationships,
                                    "sha256": hashlib.sha256(text.encode()).hexdigest()}
        checksum = schedules[str(path)]["sha256"]
        if checksum in schedule_projects and schedule_projects[checksum] != case["project_id"]:
            raise ValueError("The same schedule cannot be relabeled as independent projects")
        schedule_projects[checksum] = case["project_id"]
        case["schedule_key"] = str(path)
        ids = {a["external_id"] for a in schedules[str(path)]["activities"]}
        if any(set(g["acceptable_activity_ids"])-ids for g in case["gold"]): raise ValueError("Gold contains an ID outside its imported schedule")
    client = model_client() if args.mode == "ai" else None
    reranker = ai_status()["reranker"] if client else "llm"
    pipeline = pipeline_for(client, reranker)
    rates = json.loads(args.rates.read_text()) if args.rates else None
    if args.local_hourly_cost is not None and (not math.isfinite(args.local_hourly_cost) or args.local_hourly_cost < 0): raise ValueError("Local hourly cost must be finite and nonnegative")
    rows, index_runs = [], []
    # Each imported schedule is embedded once; cold index work is reported separately.
    for schedule in schedules.values():
        begin = time.perf_counter(); before = len(client.calls) if client else 0
        schedule["vectors"] = dict(zip((a["external_id"] for a in schedule["activities"]), client.embed([activity_card(a) for a in schedule["activities"]]))) if client else None
        duration = (time.perf_counter()-begin)*1000
        calls = client.calls[before:] if client else []
        cost = estimate_cost(calls,rates)
        if client and any(c["provider"] == "ollama" for c in calls):
            cost = duration / 3_600_000 * args.local_hourly_cost if args.local_hourly_cost is not None else None
        index_runs.append({"schedule_sha256": schedule["sha256"], "latency_ms": round(duration,2), "model_calls": calls, "cost_usd": cost})
    for case in cases:
        schedule = schedules[case["schedule_key"]]
        activities, relationships = schedule["activities"], schedule["relationships"]
        begin = time.perf_counter(); before = len(client.calls) if client else 0
        error, predictions = "", []
        try:
            inputs = case.get("rows") or [{"text":case["report"],"event_date":case.get("report_date",""),"discipline":case.get("discipline",""),"location":case.get("location","")}]
            if client and (len(inputs)>5 or sum(len(row["text"]) for row in inputs)>12_000): raise ValueError("Use the same five-row, 12,000-character AI limit as report submission")
            for row in inputs:
                if client:
                    output = analyze_report(row["text"],row.get("event_date",""),row.get("discipline",""),row.get("location",""),activities,relationships,schedule["vectors"],client,reranker)
                else:
                    output = []
                    for event in extract_events(row["text"],row.get("event_date",""),row.get("discipline",""),row.get("location","")):
                        candidates = rank_activities(event, activities); _, warnings = route_event(event,candidates)
                        output.append({**event,"candidates":candidates,"warnings":warnings,"retrieved_ids":[c["activity_id"] for c in candidates]})
                for event in output:
                    event["warnings"].extend(row.get("source_warnings",[]))
                predictions.extend(output)
        except Exception as exc:
            error = type(exc).__name__
            predictions = []
        duration = round((time.perf_counter()-begin)*1000,2)
        calls = client.calls[before:] if client else []
        cost = estimate_cost(calls,rates)
        if client and any(c["provider"] == "ollama" for c in calls):
            cost = duration / 3_600_000 * args.local_hourly_cost if args.local_hourly_cost is not None and not error else None
        unused = list(case["gold"]); claims = []
        for prediction in predictions:
            gold = next((g for g in unused if normalize(g["quote"]) == normalize(prediction["text"])), None)
            if gold: unused.remove(gold)
            acceptable = set(gold["acceptable_activity_ids"]) if gold else set()
            candidates = prediction["candidates"]; ranked = [c["activity_id"] for c in candidates]
            details = routing_details(candidates,pipeline,case["source_kind"],prediction.get("discipline",""))
            checks = actual_checks(prediction, ranked[0] if ranked else "", activities, relationships, date.fromisoformat(args.as_of))
            structural = [w for w in prediction["warnings"] if w not in {"AI suggestion requires planner confirmation", "No reliable activity match"}]
            # The model's ambiguity flag remains a structural reason for review.
            if not client: structural = [w for w in structural if w != "Several activities are plausible"]
            kind_correct = bool(gold and prediction["kind"] == gold["kind"])
            date_correct = bool(gold and prediction.get("event_date", "") == gold.get("event_date", ""))
            top1 = bool(acceptable and ranked and ranked[0] in acceptable)
            match_correct = top1 if acceptable else not ranked
            claims.append({"aligned": bool(gold), "kind_correct": kind_correct, "date_correct": date_correct,
                           "correct": bool(kind_correct and date_correct and match_correct and not gold.get("requires_review", True)) if gold else False,
                           "matchable": bool(acceptable), "top1": top1, "top3": bool(acceptable & set(ranked[:3])),
                           "retrieved": bool(acceptable & set(prediction.get("retrieved_ids", []))),
                           "requires_review": gold.get("requires_review", True) if gold else True,
                           "eligible": prediction["kind"] in {"actual_start", "actual_finish"} and bool(ranked) and not structural and not any(c["severity"] != "info" for c in checks),
                           "score": details["score"], "margin": details["margin"], "candidate_ids": ranked, "check_codes": [c["code"] for c in checks]})
        # Missing claims reduce recall and safe-review coverage instead of disappearing.
        for gold in unused:
            claims.append({"aligned": False, "kind_correct": False, "date_correct": False, "correct": False, "matchable": bool(gold["acceptable_activity_ids"]),
                           "top1": False, "top3": False, "retrieved": False, "requires_review": False, "eligible": False, "score": 0, "margin": 0})
        rows.append({"case_id": case["case_id"], "source_group_id": case["source_group_id"], "project_id": case["project_id"], "split": case["split"],
                     "schedule_sha256": schedule["sha256"],
                     "source_kind": case["source_kind"], "discipline": case.get("discipline", "") or "unspecified", "stratum": case["stratum"],
                     "gold_count": len(case["gold"]), "matchable_gold": sum(bool(g["acceptable_activity_ids"]) for g in case["gold"]),
                     "review_gold": sum(g["requires_review"] for g in case["gold"]), "predicted_count": len(predictions), "claims": claims,
                     "latency_ms": duration, "error_type": error, "model_calls": calls, "cost_usd": cost})
    policy = routing_details([],pipeline)
    stratified = {}
    for field in ("source_kind", "discipline", "stratum"):
        buckets = defaultdict(list)
        for row in rows: buckets[row[field]].append(row)
        stratified[field] = {key:summarize(values,policy["min_score"],policy["min_margin"]) for key,values in buckets.items()}
    result = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "pipeline_id": pipeline,
              "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(), "implementation_sha256": implementation_hash(), "schedule_checksums": [s["sha256"] for s in schedules.values()],
              "as_of": args.as_of, "mode": args.mode, "hardware": {"platform": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
            "rates_provenance": {k:rates.get(k) for k in ("as_of","source")} if rates else None, "local_hourly_cost_usd": args.local_hourly_cost,
              "summary": summarize(rows,policy["min_score"],policy["min_margin"]), "by_stratum": stratified,
              "cold_indexes": index_runs, "rows": rows, "label_protocol": "two-reviewer-adjudicated-v1",
              "scope": "Matching on reviewed text; does not measure OCR, speech transcription, live concurrency, or total hosting cost"}
    result["summary"]["source_cluster_precision_95ci"] = cluster_precision(rows,policy["min_score"],policy["min_margin"])
    result["summary"]["project_cluster_precision_95ci"] = cluster_precision(rows,policy["min_score"],policy["min_margin"],"project_id")
    add_index_cost(result["summary"],rows,index_runs)
    write_new(args.output,result); print("Evaluation written to " + str(args.output))


def calibrate(args):
    evaluation = json.loads(args.predictions.read_text())
    if evaluation.get("label_protocol") != "two-reviewer-adjudicated-v1": raise ValueError("Use reviewed evaluation predictions")
    if evaluation.get("implementation_sha256") != implementation_hash(): raise ValueError("The implementation changed after this evaluation; evaluate this revision first")
    if not .5 < args.target_precision < 1 or not 0 < args.min_coverage <= 1: raise ValueError("Invalid precision or coverage target")
    if not math.isfinite(args.max_p95_ms) or args.max_p95_ms <= 0 or (args.max_cost_usd is not None and (not math.isfinite(args.max_cost_usd) or args.max_cost_usd < 0)):
        raise ValueError("Latency and cost budgets must be finite and nonnegative")
    rows = evaluation["rows"]
    calibration = [r for r in rows if r["split"] == "calibration"]
    holdout = [r for r in rows if r["split"] == "holdout"]
    for key in ("case_id", "project_id", "source_group_id"):
        if {r[key] for r in calibration} & {r[key] for r in holdout}: raise ValueError("Evaluation contains split leakage")
    candidates = []
    for score in [n/40 for n in range(41)] + [.38]:
        for margin in [n/40 for n in range(41)] + [.12]:
            metrics = summarize(calibration, score, margin)
            lower = metrics["staging_precision_95ci"]["lower"]
            if metrics["staged_actuals"] >= 100 and lower is not None and lower >= args.target_precision and (metrics["staging_coverage"] or 0) >= args.min_coverage:
                candidates.append((metrics["staging_coverage"],lower,score,margin,metrics))
    chosen = max(candidates, key=lambda c:(c[0],c[1],c[2],c[3])) if candidates else None
    score, margin = (chosen[2],chosen[3]) if chosen else (.38,.12)
    metrics = summarize(holdout, score, margin)
    add_index_cost(metrics,holdout,evaluation["cold_indexes"])
    failures = []
    if not chosen: failures.append("No calibration threshold meets precision, support and coverage targets")
    for split,subset in [("calibration",calibration),("holdout",holdout)]:
        for key in ("source_group_id","project_id"):
            interval = cluster_precision(subset,score,margin,key)
            if split == "holdout": metrics[key+"_precision_95ci"] = interval
            if (interval["lower"] or 0) < args.target_precision:
                failures.append(split+" clustered precision confidence gate failed for "+key)
    for split, subset in [("calibration",calibration),("holdout",holdout)]:
        if len(subset) < 500: failures.append(split + " needs at least 500 reviewed reports")
        if len({r["source_group_id"] for r in subset}) < 500: failures.append(split + " needs at least 500 independent source groups")
        if len({r["project_id"] for r in subset}) < 3: failures.append(split + " needs at least three independent projects")
    if metrics["staged_actuals"] < 100 or (metrics["staging_precision_95ci"]["lower"] or 0) < args.target_precision:
        failures.append("Holdout precision confidence or support gate failed")
    if (metrics["staging_coverage"] or 0) < args.min_coverage: failures.append("Holdout coverage gate failed")
    if (metrics["error_rate"] or 0) > .01: failures.append("Holdout report failure rate exceeds one percent")
    if not metrics["report_latency_ms"]["p95"] or metrics["report_latency_ms"]["p95"] > args.max_p95_ms: failures.append("Holdout latency budget failed")
    if metrics["total_cost_usd"] is None: failures.append("Complete priced usage or explicit local compute costs are required")
    if args.max_cost_usd is None or metrics["cost_per_report_usd"] is None or metrics["cost_per_report_usd"] > args.max_cost_usd:
        failures.append("An explicit cost budget per report must pass")
    strata = {}
    for key in ("source_kind", "discipline", "stratum"):
        strata[key] = {}
        buckets = defaultdict(list)
        for row in holdout: buckets[row[key]].append(row)
        for name, subset in buckets.items():
            values = summarize(subset,score,margin); strata[key][name] = values
            if len(subset) < 50:
                failures.append(f"Insufficient report support for {key}={name}")
            review_only = all(claim.get("requires_review") or not claim["aligned"] for row in subset for claim in row["claims"])
            if review_only:
                if sum(r["review_gold"] for r in subset) < 30 or (values["safe_review_recall"] or 0) < args.target_precision:
                    failures.append(f"Review routing coverage failed for {key}={name}")
            elif values["staged_actuals"] < 30 or (values["staging_precision"] or 0) < args.target_precision:
                failures.append(f"Staging support or precision failed for {key}={name}")
    for required in args.require_stratum:
        if required not in strata["stratum"]: failures.append("Missing required input stratum: "+required)
    artifact = {"schema_version": 1, "policy_id": "policy-"+hashlib.sha256(args.predictions.read_bytes()).hexdigest()[:16],
                "pipeline_id": evaluation["pipeline_id"], "dataset_sha256": evaluation["dataset_sha256"],
                "implementation_sha256": evaluation.get("implementation_sha256"),
                "status": "validated" if not failures else "candidate", "holdout_passed": not failures,
                "calibration_cases": len(calibration), "holdout_cases": len(holdout), "min_score": score, "min_margin": margin,
                "target_precision": args.target_precision, "calibration_metrics": chosen[4] if chosen else summarize(calibration,score,margin),
                "holdout_metrics": metrics, "holdout_strata": strata, "failed_gates": failures,
                "budgets": {"max_p95_ms": args.max_p95_ms, "max_cost_per_report_usd": args.max_cost_usd},
                "required_strata": args.require_stratum, "created_at": datetime.now(timezone.utc).isoformat()}
    artifact["validated_sources"] = sorted({r["source_kind"] for r in holdout})
    artifact["validated_disciplines"] = sorted({r["discipline"].casefold() for r in holdout})
    write_new(args.output,artifact)
    print("Policy " + artifact["status"] + ": " + str(args.output))


def add_index_cost(metrics,rows,index_runs):
    hashes = {row["schedule_sha256"] for row in rows}
    costs = [run["cost_usd"] for run in index_runs if run["schedule_sha256"] in hashes]
    metrics["index_cost_usd"] = round(sum(costs),8) if all(c is not None for c in costs) else None
    warm, cold = metrics["total_cost_usd"],metrics["index_cost_usd"]
    metrics["including_index_cost_usd"] = round(warm+cold,8) if warm is not None and cold is not None else None
    metrics["cost_per_report_usd"] = round((warm+cold)/len(rows),8) if warm is not None and cold is not None and rows else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    export = commands.add_parser("export-labels"); export.add_argument("--output-dir",type=Path,required=True); export.set_defaults(run=export_labels)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--cases",type=Path,required=True); evaluate_parser.add_argument("--mode",choices=["rules","ai"],required=True)
    evaluate_parser.add_argument("--output",type=Path,required=True); evaluate_parser.add_argument("--rates",type=Path)
    evaluate_parser.add_argument("--local-hourly-cost",type=float); evaluate_parser.add_argument("--as-of",default=date.today().isoformat())
    evaluate_parser.set_defaults(run=evaluate)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--predictions",type=Path,required=True); calibration.add_argument("--output",type=Path,required=True)
    calibration.add_argument("--target-precision",type=float,default=.98); calibration.add_argument("--min-coverage",type=float,default=.1)
    calibration.add_argument("--max-p95-ms",type=float,default=15_000); calibration.add_argument("--max-cost-usd",type=float)
    calibration.add_argument("--require-stratum",action="append",default=["clean","colloquial","ambiguous","unmatched","ocr-noisy","negated","multi-event"])
    calibration.set_defaults(run=calibrate)
    args = parser.parse_args()
    try: args.run(args)
    except (ValueError,KeyError,OSError,RuntimeError,sqlite3.Error) as exc: parser.exit(2,str(exc)+"\n")


if __name__ == "__main__": main()
