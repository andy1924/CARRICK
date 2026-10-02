"""Read-only schedule scenarios using existing activities and TASKPRED relationships.

This elapsed-day model is a planning aid. P6 remains the master calendar engine.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict
from datetime import date, timedelta


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _iso(value: float) -> str:
    return (date.fromordinal(math.floor(value)) + timedelta(days=math.ceil(value % 1))).isoformat()


def schedule_analytics(activities: list[dict], relationships: list[dict], events: list[dict],
                       as_of: str, duration_factor: float = 1.0, risk_samples: int = 200) -> dict:
    day = date.fromisoformat(as_of)
    if not .5 <= duration_factor <= 3 or not math.isfinite(duration_factor):
        raise ValueError("Duration factor must be between 0.5 and 3")
    if len(activities) > 10000:
        raise ValueError("Scenario analysis supports up to 10,000 activities")
    today = day.toordinal()
    by_id = {activity["external_id"]: dict(activity) for activity in activities}
    warnings = []
    # Overlay approved actuals without changing the imported schedule snapshot.
    # Forecast notes are considered only after a planner records them against an ID.
    for event in events:
        task = by_id.get(event.get("selected_activity"))
        if not task or not _date(event.get("event_date")):
            continue
        kind, status = event["kind"], event["status"]
        if kind in {"actual_start", "actual_finish"} and status in {"approved", "exported"}:
            task[kind] = event["event_date"]
        elif kind in {"forecast_start", "forecast_finish", "blocked"} and status == "recorded":
            task[kind] = event["event_date"]
    included, excluded = {}, []
    for task_id, task in by_id.items():
        start, finish = _date(task.get("planned_start")), _date(task.get("planned_finish"))
        if not start or not finish or finish < start:
            excluded.append(task_id)
            continue
        actual_start, actual_finish = _date(task.get("actual_start")), _date(task.get("actual_finish"))
        if actual_start and actual_start > day:
            actual_start = None
        if actual_finish and actual_finish > day:
            actual_finish = None
        if actual_start and actual_finish and actual_finish < actual_start:
            excluded.append(task_id)
            warnings.append(f"{task_id}: actual finish precedes actual start")
            continue
        task.update(plan_start=start.toordinal(), plan_finish=finish.toordinal(),
                    duration=(finish-start).days, fixed=bool(actual_start or actual_finish), complete=bool(actual_finish),
                    start_actual=actual_start.toordinal() if actual_start else None,
                    finish_actual=actual_finish.toordinal() if actual_finish else None)
        included[task_id] = task
    incoming, outgoing = defaultdict(list), defaultdict(list)
    indegree = {task_id: 0 for task_id in included}
    unsupported, missing_edges = 0, 0
    for relation in relationships:
        predecessor, successor = relation["predecessor"], relation["successor"]
        kind = relation.get("kind", "FS").removeprefix("PR_")
        if predecessor not in included or successor not in included:
            missing_edges += 1
            continue
        if kind not in {"FS", "SS", "FF", "SF"}:
            unsupported += 1
            continue
        try:
            lag = float(relation.get("lag") or 0) / 24
            if not math.isfinite(lag):
                raise ValueError
        except (TypeError, ValueError):
            unsupported += 1
            continue
        edge = {"predecessor": predecessor, "successor": successor, "kind": kind, "lag": lag}
        incoming[successor].append(edge)
        outgoing[predecessor].append(edge)
        indegree[successor] += 1
    ready = [task_id for task_id, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        task_id = heapq.heappop(ready)
        order.append(task_id)
        for edge in outgoing[task_id]:
            indegree[edge["successor"]] -= 1
            if indegree[edge["successor"]] == 0:
                heapq.heappush(ready, edge["successor"])
    assumptions = ["Elapsed calendar days; no P6 working calendars or resource leveling",
                   "XER relationship lags converted from hours using 24 hours per elapsed day",
                   "Unstarted work uses planned duration; started work scales its remaining planned duration, with one day assumed for overdue unfinished work",
                   "Risk envelope uses illustrative triangular duration factors 0.8 / 1.0 / 1.5; it is not calibrated probability",
                   "Only approved actuals and planner-recorded forecast dates enter this scenario"]
    if excluded:
        warnings.append(f"{len(excluded)} activities excluded because usable planned dates or actual sequences are missing")
    if missing_edges:
        warnings.append(f"{missing_edges} dependencies omitted because an endpoint is excluded or outside this import")
    if unsupported:
        warnings.append(f"{unsupported} dependency records have unsupported types or invalid lag values")
    if not relationships:
        warnings.append("No dependency graph is available. Dates can be projected, but critical path cannot be determined.")
    if len(order) != len(included):
        return {"available": False, "reason": "The dependency graph contains a cycle. Resolve it in the master schedule.",
                "cycle_affected_ids": sorted(task_id for task_id, degree in indegree.items() if degree > 0),
                "warnings": warnings, "assumptions": assumptions, "activities": [], "as_of": as_of}
    if not order:
        return {"available": False, "reason": "Import activities with valid planned start and finish dates to build a scenario.",
                "warnings": warnings, "assumptions": assumptions, "activities": [], "as_of": as_of}

    def offset(edge: dict, durations: dict) -> float:
        pred, succ, kind = edge["predecessor"], edge["successor"], edge["kind"]
        return edge["lag"] + (durations[pred] if kind in {"FS", "FF"} else 0) - (durations[succ] if kind in {"FF", "SF"} else 0)

    def project(randomizer=None):
        durations, starts, finishes, violations = {}, {}, {}, []
        for task_id in order:
            task = included[task_id]
            multiplier = duration_factor * (randomizer.triangular(.8, 1.5, 1.0) if randomizer else 1)
            duration = task["duration"] * multiplier
            start_actual, finish_actual = task["start_actual"], task["finish_actual"]
            if finish_actual is not None:
                start = start_actual if start_actual is not None else finish_actual - task["duration"]
                duration = finish_actual - start
            elif start_actual is not None:
                start = start_actual
                elapsed = max(0, today - start)
                remaining = max(1, task["duration"] - elapsed) if task["duration"] else 0
                duration = elapsed + remaining * multiplier
            else:
                start = max(today, task["plan_start"])
            forecast_start, forecast_finish = _date(task.get("forecast_start")), _date(task.get("forecast_finish"))
            if not task["fixed"] and forecast_start:
                start = max(start, forecast_start.toordinal())
            if finish_actual is None and forecast_finish:
                duration = max(duration, forecast_finish.toordinal() - start)
            durations[task_id] = duration
            for edge in incoming[task_id]:
                constraint = starts[edge["predecessor"]] + offset(edge, durations)
                if task["fixed"]:
                    if start + .001 < constraint:
                        violations.append({"predecessor": edge["predecessor"], "successor": task_id, "kind": edge["kind"]})
                else:
                    start = max(start, constraint)
            starts[task_id], finishes[task_id] = start, start + duration
        return starts, finishes, durations, violations

    starts, finishes, durations, violations = project()
    project_finish = max(finishes.values())
    baseline_finish = max(task["plan_finish"] for task in included.values())
    latest = {task_id: project_finish - durations[task_id] for task_id in order}
    for task_id in reversed(order):
        for edge in outgoing[task_id]:
            latest[task_id] = min(latest[task_id], latest[edge["successor"]] - offset(edge, durations))
    criticality = defaultdict(int)
    envelope = []
    rng = random.Random(42)
    for _ in range(risk_samples):
        sample_starts, sample_finishes, sample_durations, _ = project(rng)
        end = max(sample_finishes.values())
        envelope.append(end)
        sample_latest = {task_id: end - sample_durations[task_id] for task_id in order}
        for task_id in reversed(order):
            for edge in outgoing[task_id]:
                sample_latest[task_id] = min(sample_latest[task_id], sample_latest[edge["successor"]] - offset(edge, sample_durations))
            if sample_latest[task_id] - sample_starts[task_id] <= .01 and not included[task_id]["complete"]:
                criticality[task_id] += 1
    rows, wbs = [], {}
    for task_id in order:
        task = included[task_id]
        slip = max(0, math.ceil(finishes[task_id] - task["plan_finish"]))
        slack = max(0, round(latest[task_id] - starts[task_id], 1))
        critical = bool(relationships) and not task["complete"] and slack <= .01
        rows.append({"activity_id": task_id, "name": task["name"], "wbs": task.get("wbs") or "Unassigned",
                     "planned_finish": _iso(task["plan_finish"]), "forecast_start": _iso(starts[task_id]),
                     "forecast_finish": _iso(finishes[task_id]), "slip_days": slip, "float_days": slack,
                     "critical": critical, "criticality_percent": round(100 * criticality[task_id] / risk_samples) if risk_samples and relationships else None,
                     "complete": task["complete"], "blocked": bool(task.get("blocked")) and not task["complete"],
                     "overdue": not task["complete"] and task["plan_finish"] < today})
        group = wbs.setdefault(task.get("wbs") or "Unassigned", {"wbs": task.get("wbs") or "Unassigned", "total": 0, "complete": 0, "overdue": 0, "critical": 0})
        group["total"] += 1
        group["complete"] += task["complete"]
        group["overdue"] += rows[-1]["overdue"]
        group["critical"] += critical
    envelope.sort()
    return {"available": True, "as_of": as_of, "duration_factor": duration_factor,
            "planned_finish": _iso(baseline_finish), "projected_finish": _iso(project_finish),
            "project_slip_days": max(0, math.ceil(project_finish-baseline_finish)),
            "risk": {"p50_finish": _iso(envelope[int((len(envelope)-1) * .5)]) if envelope else None,
                     "p80_finish": _iso(envelope[int((len(envelope)-1) * .8)]) if envelope else None,
                     "samples": risk_samples, "illustrative": True},
            "counts": {"activities": len(rows), "complete": sum(row["complete"] for row in rows),
                       "critical": sum(row["critical"] for row in rows), "overdue": sum(row["overdue"] for row in rows),
                       "blocked": sum(row["blocked"] for row in rows)},
            "activities": sorted(rows, key=lambda row: (row["complete"], not row["critical"], -row["slip_days"], row["activity_id"])),
            "wbs": list(wbs.values()), "sequence_conflicts": violations,
            "excluded_ids": excluded, "warnings": warnings, "assumptions": assumptions}
