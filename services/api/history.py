"""Parameterized, paginated history queries with canonical report source groups."""
import json
from datetime import date


def enrich(db, events):
    groups = {event.get("duplicate_group_id") or event["report_id"] for event in events}
    sources, similarities = {}, {}
    for group_id in groups:
        sources[group_id] = [dict(row) for row in db.execute("""SELECT id,source_kind,filename,created_at,capture_asset_id,duplicate_of
                              FROM reports WHERE duplicate_group_id=? ORDER BY created_at,id""", (group_id,))]
        similarities[group_id] = [dict(row) for row in db.execute("""SELECT report_id,related_id,similarity,reason FROM report_similarities
                            WHERE report_id=? OR related_id=?""", (group_id,group_id))]
    for event in events:
        group_id = event.get("duplicate_group_id") or event["report_id"]
        event.update(duplicate_group_id=group_id, sources=sources[group_id], source_count=len(sources[group_id]), similar_reports=similarities[group_id])
        event["decisions"] = [dict(row) for row in db.execute("SELECT action,actor,detail,created_at FROM audit WHERE event_id=? ORDER BY id",(event["id"],))]
    return events


def query_history(db, version_id, params, decode):
    limit, offset = int(params.get("limit", 50)), int(params.get("offset", 0))
    if not 1 <= limit <= 200 or offset < 0: raise ValueError("History page size must be 1–200 and offset nonnegative")
    for value in params.values():
        if len(str(value)) > 300: raise ValueError("History filter values must be 300 characters or fewer")
    clauses, values = ["r.version_id=?"], [version_id]
    if params.get("status") not in {None, "", "all"}:
        status = params["status"]
        if status == "pending": clauses.append("e.status IN ('staged','needs_review')")
        elif status in {"approved", "exported", "recorded", "rejected", "duplicate"}: clauses.append("e.status=?"); values.append(status)
        else: raise ValueError("Unknown history status")
    if params.get("activity"):
        clauses.append("(e.selected_activity=? COLLATE NOCASE OR instr(lower(e.candidates),lower(?))>0)")
        values.extend([params["activity"], '"activity_id": ' + json.dumps(params["activity"])])
    if params.get("discipline"):
        clauses.append("e.discipline=? COLLATE NOCASE"); values.append(params["discipline"])
    if params.get("q"):
        clauses.append("(instr(lower(e.text),lower(?))>0 OR instr(lower(e.candidates),lower(?))>0 OR instr(lower(coalesce(e.selected_activity,'')),lower(?))>0)")
        values.extend([params["q"]]*3)
    source_conditions = ["s.duplicate_group_id=r.duplicate_group_id"]
    source_values = []
    if params.get("source"):
        if params["source"] not in {"text", "document", "voice", "spreadsheet"}: raise ValueError("Unknown report source")
        source_conditions.append("s.source_kind=?"); source_values.append(params["source"])
    if params.get("source_query"):
        source_conditions.append("(instr(lower(coalesce(s.filename,'')),lower(?))>0 OR s.id=? OR s.capture_asset_id=?)")
        source_values.extend([params["source_query"]]*3)
    date_field = params.get("date_field", "event_date")
    if date_field not in {"event_date", "received_at", "decided_at"}: raise ValueError("Unknown history date field")
    if params.get("date_from") and params.get("date_to") and params["date_from"] > params["date_to"]:
        raise ValueError("Start date must not follow end date")
    for name, operator in [("date_from", ">="), ("date_to", "<=")]:
        if params.get(name):
            date.fromisoformat(params[name])
            if date_field == "received_at": source_conditions.append(f"substr(s.created_at,1,10){operator}?"); source_values.append(params[name])
            else: clauses.append(f"substr(e.{date_field},1,10){operator}?"); values.append(params[name])
    if len(source_conditions) > 1:
        clauses.append("EXISTS (SELECT 1 FROM reports s WHERE " + " AND ".join(source_conditions) + ")"); values.extend(source_values)
    if params.get("duplicates") == "grouped":
        clauses.append("(SELECT count(*) FROM reports s WHERE s.duplicate_group_id=r.duplicate_group_id)>1")
    elif params.get("duplicates") not in {None, "", "all"}: raise ValueError("Unknown duplicate filter")
    base = "FROM events e JOIN reports r ON r.id=e.report_id WHERE " + " AND ".join(clauses)
    total = db.execute("SELECT count(*) " + base, values).fetchone()[0]
    rows = db.execute("""SELECT e.*,r.source_kind,r.filename,r.created_at AS received_at,r.capture_asset_id,r.duplicate_group_id """ + base +
                      " ORDER BY r.created_at DESC,e.rowid DESC LIMIT ? OFFSET ?", [*values,limit,offset]).fetchall()
    events = enrich(db, [decode(row) for row in rows])
    return {"events": events, "total": total, "limit": limit, "offset": offset, "has_more": offset+len(events)<total, "schedule_version": version_id}
