"""Actual-date invariants and relationship checks over a reviewed schedule overlay."""

import math
import re
from collections import defaultdict, deque
from datetime import date, timedelta


def _date(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def graph_issues(activities, relationships):
    ids = {activity["external_id"] for activity in activities}
    issues, degree, outgoing = [], {task_id: 0 for task_id in ids}, defaultdict(list)
    for edge in relationships:
        pred, succ = edge["predecessor"], edge["successor"]
        if pred not in ids or succ not in ids:
            issues.append({"code": "missing_dependency_endpoint", "severity": "warning", "message": f"Dependency {pred} → {succ} has an endpoint outside this import"})
            continue
        outgoing[pred].append(succ); degree[succ] += 1
        kind = edge.get("kind", "").removeprefix("PR_")
        try:
            valid_lag = math.isfinite(float(edge.get("lag") or 0))
        except (TypeError, ValueError):
            valid_lag = False
        if kind not in {"FS", "SS", "FF", "SF"} or not valid_lag:
            issues.append({"code": "unsupported_dependency", "severity": "warning", "message": f"Dependency {pred} → {succ} has an unsupported type or lag"})
    queue = deque(task_id for task_id, count in degree.items() if not count)
    count = 0
    while queue:
        task_id = queue.popleft(); count += 1
        for successor in outgoing[task_id]:
            degree[successor] -= 1
            if not degree[successor]: queue.append(successor)
    if count < len(ids):
        issues.append({"code": "dependency_cycle", "severity": "warning", "message": "The imported dependency graph contains a cycle; sequence checks are incomplete"})
    return issues


def actual_checks(event, activity_id, activities, relationships, today: date, include_graph=True):
    if event["kind"] not in {"actual_start", "actual_finish"}:
        task = next((a for a in activities if a["external_id"] == activity_id), None)
        issues = []
        def note(code,message): issues.append({"code":code,"severity":"warning","message":message})
        if task:
            if event["kind"] == "not_started" and _date(task.get("actual_start")):
                note("contradictory_progress","This report says work has not started, but an actual start is already recorded")
            if event["kind"] in {"in_progress","partial_progress","forecast_start","forecast_finish"} and _date(task.get("actual_finish")):
                note("completed_activity_claim","This activity already has an actual finish; compare the reported scope")
            reference, start = _date(event.get("event_date")), _date(task.get("actual_start"))
            if event["kind"] == "forecast_finish" and reference and start and reference < start:
                note("forecast_before_start","Forecast finish precedes the recorded actual start")
        if event["kind"] == "partial_progress" and any(float(value)>100 for value in re.findall(r"(\d+(?:\.\d+)?)\s*%",event.get("text",""))):
            note("invalid_progress_percentage","Reported completion exceeds 100 percent; confirm the units and scope")
        return issues
    issues = []
    def add(code, severity, message):
        issues.append({"code": code, "severity": severity, "message": message})
    by_id = {activity["external_id"]: dict(activity) for activity in activities}
    task = by_id.get(activity_id)
    proposed = _date(event.get("event_date"))
    if not proposed:
        add("missing_actual_date", "error", "A valid actual date is required")
    elif proposed > today:
        add("future_actual", "error", "An actual event date cannot be in the future")
    if not task:
        add("unknown_activity", "error", "Choose an activity from the imported schedule")
        return issues
    known = _date(task.get(event["kind"]))
    if proposed and known:
        if proposed != known:
            add("conflicting_actual", "error", f"{activity_id} already has {event['kind'].replace('_', ' ')} on {known.isoformat()}")
        else:
            add("duplicate_actual", "info", "This actual date is already recorded; a second update is unnecessary")
    if proposed:
        task[event["kind"]] = proposed.isoformat()
    start, finish = _date(task.get("actual_start")), _date(task.get("actual_finish"))
    if start and finish and finish < start:
        add("finish_before_start", "error", "Actual finish precedes actual start")
    if event["kind"] == "actual_finish" and not start:
        add("missing_actual_start", "warning", "Actual start is not recorded; explain the finish-only approval")
    if include_graph:
        issues.extend(graph_issues(activities, relationships))
    for edge in relationships:
        if activity_id not in {edge["predecessor"], edge["successor"]}:
            continue
        pred, succ = by_id.get(edge["predecessor"]), by_id.get(edge["successor"])
        kind = edge.get("kind", "").removeprefix("PR_")
        if not pred or not succ or kind not in {"FS", "SS", "FF", "SF"}:
            continue
        try:
            lag = float(edge.get("lag") or 0) / 24
            if not math.isfinite(lag): continue
        except (TypeError, ValueError):
            continue
        pred_field = "actual_finish" if kind[0] == "F" else "actual_start"
        succ_field = "actual_finish" if kind[1] == "F" else "actual_start"
        predecessor_date, successor_date = _date(pred.get(pred_field)), _date(succ.get(succ_field))
        if not successor_date:
            continue
        if not predecessor_date:
            if edge["successor"] == activity_id:
                add("missing_predecessor_actual", "warning", f"{kind}: {edge['predecessor']} has no {pred_field.replace('_', ' ')}")
            continue
        if successor_date.toordinal() < predecessor_date.toordinal() + lag:
            add("sequence_conflict", "warning", f"{kind}: {edge['successor']} {succ_field.replace('_', ' ')} violates {edge['predecessor']} plus {edge.get('lag') or 0}h lag")
        if lag % 1 and predecessor_date == successor_date:
            add("date_precision", "warning", f"{kind}: date-only actuals cannot verify an hourly lag on the same day")
    return list({(item["code"], item["message"]): item for item in issues}.values())


def competing_claims(event, other_events, activity_id):
    """Pending suggestions are warnings, never authoritative schedule dates."""
    issues = []
    for other in other_events:
        if other.get("id") and other.get("id") == event.get("id"): continue
        suggested = other.get("selected_activity") or (other.get("candidates") or [{}])[0].get("activity_id")
        if not activity_id or suggested != activity_id: continue
        same_kind = event["kind"] == other["kind"] and event["kind"] in {"actual_start","actual_finish"}
        different_dates = _date(event.get("event_date")) and _date(other.get("event_date")) and _date(event["event_date"]) != _date(other["event_date"])
        negation = {event["kind"],other["kind"]} & {"not_started"} and {event["kind"],other["kind"]} & {"actual_start","actual_finish"}
        reversed_pair = False
        if {event["kind"],other["kind"]} == {"actual_start","actual_finish"}:
            start = _date((event if event["kind"] == "actual_start" else other).get("event_date"))
            finish = _date((event if event["kind"] == "actual_finish" else other).get("event_date"))
            reversed_pair = bool(start and finish and finish < start)
        if same_kind and different_dates or negation or reversed_pair:
            issues.append({"code":"competing_claim","severity":"warning","message":f"Another pending claim for {activity_id} conflicts with this proposal ({other.get('id') or 'same report'}); compare both sources"})
    return list({item["message"]:item for item in issues}.values())
