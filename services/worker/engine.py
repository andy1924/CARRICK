"""Dependency-free schedule parsing, event extraction, and candidate ranking."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from services.worker.routing import routing_details


ALIASES = {
    "poured": "pour", "pouring": "pour", "concrete": "concrete",
    "erected": "erect", "erection": "erect", "installed": "install",
    "installation": "install", "welded": "weld", "welding": "weld",
    "tested": "test", "testing": "test", "excavated": "excavate",
    "excavation": "excavate", "foundation": "foundation", "foundations": "foundation",
    "pipeline": "pipe", "piping": "pipe", "cabling": "cable",
    "pulled": "pull", "completed": "complete", "finished": "finish",
}
STOP = {"the", "a", "an", "for", "of", "on", "in", "at", "to", "we", "team", "work", "was", "is", "has", "have", "and", "today", "yesterday", "started", "finished", "completed", "pending"}


class ScheduleError(ValueError):
    pass


def parse_schedule(content: str, filename: str) -> tuple[list[dict], list[dict], str]:
    if filename.lower().endswith(".xer"):
        return parse_xer(content)
    if filename.lower().endswith(".csv"):
        return parse_schedule_csv(content)
    raise ScheduleError("Schedule must be an XER or CSV file")


def parse_xer(content: str) -> tuple[list[dict], list[dict], str]:
    tables: dict[str, list[dict]] = {}
    table = None
    fields: list[str] = []
    for line in content.splitlines():
        parts = line.split("\t")
        marker = parts[0]
        if marker == "%T":
            table = parts[1] if len(parts) > 1 else None
            fields = []
        elif marker == "%F" and table:
            fields = parts[1:]
        elif marker == "%R" and table and fields:
            values = parts[1:]
            tables.setdefault(table, []).append(dict(zip(fields, values)))
    rows = tables.get("TASK", [])
    if not rows:
        raise ScheduleError("XER has no TASK records")
    wbs_rows = {r.get("wbs_id"): r for r in tables.get("PROJWBS", [])}

    def wbs_path(wbs_id: str) -> str:
        names, seen = [], set()
        while wbs_id and wbs_id in wbs_rows and wbs_id not in seen:
            seen.add(wbs_id)
            row = wbs_rows[wbs_id]
            names.append(row.get("wbs_name") or row.get("wbs_short_name") or wbs_id)
            wbs_id = row.get("parent_wbs_id", "")
        return " / ".join(reversed(names))

    activities = []
    for row in rows:
        external_id = row.get("task_code") or row.get("task_id")
        if not external_id:
            raise ScheduleError("TASK record is missing an activity ID")
        activities.append({
            "source_key": row.get("task_id") or external_id,
            "external_id": external_id,
            "name": row.get("task_name") or external_id,
            "wbs": wbs_path(row.get("wbs_id", "")),
            "discipline": "",
            "location": row.get("location_id", ""),
            "planned_start": row.get("target_start_date", ""),
            "planned_finish": row.get("target_end_date", ""),
            "actual_start": row.get("act_start_date", ""),
            "actual_finish": row.get("act_end_date", ""),
            "status": row.get("status_code", ""),
        })
    # TASKPRED references internal task_id values. Resolve them to the same
    # external TASK IDs shown to planners before storing relationship context.
    task_codes = {a["source_key"]: a["external_id"] for a in activities}
    relationships = [{
        "predecessor": task_codes.get(r.get("pred_task_id", ""), "unresolved-task:"+r.get("pred_task_id", "")),
        "successor": task_codes.get(r.get("task_id", ""), "unresolved-task:"+r.get("task_id", "")),
        "kind": r.get("pred_type", "FS"),
        "lag": r.get("lag_hr_cnt", "0"),
    } for r in tables.get("TASKPRED", []) if r.get("pred_task_id") and r.get("task_id")]
    _check_unique(activities)
    return activities, relationships, "xer"


def parse_schedule_csv(content: str) -> tuple[list[dict], list[dict], str]:
    reader = csv.DictReader(io.StringIO(content))
    required = {"activity_id", "activity_name"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ScheduleError("Schedule CSV needs activity_id and activity_name columns")
    activities = []
    for row in reader:
        external_id = (row.get("activity_id") or "").strip()
        if not external_id:
            continue
        activities.append({
            "source_key": external_id, "external_id": external_id,
            "name": (row.get("activity_name") or external_id).strip(),
            "wbs": (row.get("wbs") or "").strip(),
            "discipline": (row.get("discipline") or "").strip(),
            "location": (row.get("location") or "").strip(),
            "planned_start": (row.get("planned_start") or "").strip(),
            "planned_finish": (row.get("planned_finish") or "").strip(),
            "actual_start": (row.get("actual_start") or "").strip(),
            "actual_finish": (row.get("actual_finish") or "").strip(),
            "status": (row.get("status") or "").strip(),
        })
    if not activities:
        raise ScheduleError("Schedule CSV has no activities")
    _check_unique(activities)
    return activities, [], "csv"


def _check_unique(activities: list[dict]) -> None:
    ids = [row["external_id"] for row in activities]
    if len(ids) != len(set(ids)):
        raise ScheduleError("Schedule contains duplicate activity IDs")


def extract_events(text: str, event_date: str = "", discipline: str = "", location: str = "") -> list[dict]:
    chunks = [s.strip(" .\t") for s in re.split(r"[;\n]+|(?<=[.!?])\s+", text) if s.strip()]
    result = []
    for chunk in chunks:
        lower = chunk.lower()
        future = bool(re.search(r"\b(will|tomorrow|next week|planned|expect(?:ed)?)\b", lower))
        negated = bool(re.search(r"\b(not started|hasn't started|have not started|not finished|not completed|pending)\b", lower))
        if future:
            kind = "forecast_finish" if re.search(r"\b(finish|complete|done)\b", lower) else "forecast_start"
        elif negated:
            kind = "not_started" if "start" in lower or "pending" in lower else "in_progress"
        elif re.search(r"\b(complete|completes|completed|finish|finishes|finished|done|poured|erected|installed|tested|welded)\b", lower):
            kind = "actual_finish"
        elif re.search(r"\b(start|starts|started|began|commenced)\b", lower):
            kind = "actual_start"
        elif re.search(r"\b(blocked|delayed|held)\b", lower):
            kind = "blocked"
        elif re.search(r"\b(\d+\s*%|in progress|ongoing)\b", lower):
            kind = "partial_progress"
        else:
            kind = "unknown"
        iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", chunk)
        resolved = iso.group(1) if iso else event_date
        if re.search(r"\byesterday\b", lower) and event_date:
            resolved = (date.fromisoformat(event_date) - timedelta(days=1)).isoformat()
        elif re.search(r"\btomorrow\b", lower) and event_date:
            resolved = (date.fromisoformat(event_date) + timedelta(days=1)).isoformat()
        elif re.search(r"\btoday\b", lower) and event_date:
            resolved = event_date
        result.append({"text": chunk, "kind": kind, "event_date": resolved,
                       "discipline": discipline.strip(), "location": location.strip()})
    return result


def tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", value.lower())
    return {ALIASES.get(word, word) for word in words if word not in STOP and len(word) > 1}


def rank_activities(event: dict, activities: list[dict], limit: int = 5) -> list[dict]:
    query = tokens(event["text"])
    location = tokens(event.get("location", ""))
    discipline = tokens(event.get("discipline", ""))
    ranked = []
    for activity in activities:
        title = tokens(activity["name"])
        context = tokens(" ".join([activity.get("wbs", ""), activity.get("location", ""), activity.get("discipline", ""), activity["external_id"]]))
        overlap = len(query & title) / max(1, len(query | title))
        context_overlap = len(query & context) / max(1, len(query))
        similarity = SequenceMatcher(None, " ".join(sorted(query)), " ".join(sorted(title))).ratio()
        score = 0.55 * overlap + 0.25 * context_overlap + 0.20 * similarity
        if location:
            score += 0.16 if location & (title | context) else -0.08
        if discipline and discipline & context:
            score += 0.06
        if event["kind"] == "actual_start" and activity.get("actual_finish"):
            score -= 0.12
        ranked.append({"activity_id": activity["external_id"], "name": activity["name"],
                       "wbs": activity.get("wbs", ""), "location": activity.get("location", ""),
                       "score": round(max(0, min(1, score)), 3),
                       "evidence": sorted(query & (title | context))})
    return sorted(ranked, key=lambda x: (-x["score"], x["activity_id"]))[:limit]


def route_event(event: dict, candidates: list[dict]) -> tuple[str, list[str]]:
    routing = routing_details(candidates)
    warnings = []
    if event["kind"] not in {"actual_start", "actual_finish"}:
        warnings.append("Event does not set an actual date")
    if not event["event_date"] and event["kind"] in {"actual_start", "actual_finish"}:
        warnings.append("Actual date is missing")
    if len(candidates) > 1 and routing["margin"] < routing["min_margin"]:
        warnings.append("Several activities are plausible")
    if not candidates or candidates[0]["score"] < routing["min_score"]:
        warnings.append("No reliable activity match")
    return ("staged" if not warnings else "needs_review"), warnings
