"""Local Carrick API and static web server. Run with `python3 -m services.api.app`."""

from __future__ import annotations

import csv
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from services.worker.engine import ScheduleError, extract_events, parse_schedule, rank_activities, route_event
from services.worker.ai import AiResponseError, AiUnavailable, OpenAIClient, ai_status, analyze_report, activity_card, rank_event, model_client, load_local_env
from services.worker.ingest import document_rows
from services.worker.capture import capture_status, decode_file, extract_document, transcribe_audio
from services.worker.analytics import schedule_analytics
from services.worker.duplicates import identity, similar_reports
from services.worker.validation import actual_checks, competing_claims
from services.worker.routing import routing_details, pipeline_for, policy_for
from services.worker.usage import active_calls
from services.api.history import enrich, query_history
from services.api.quality import quality_status
from services.api import auth
from services.worker.xer_output import progress_output


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
DB_PATH = Path(os.environ.get("CARRICK_DB", ROOT / "data" / "private" / "carrick.sqlite3"))
MAX_BODY = 16_000_000
CAPTURE_DIR = DB_PATH.parent / "captures"
_report_lock = threading.Lock()


class ScheduleConflict(ValueError):
    pass


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    DB_PATH.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def db_session():
    db = connection()
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db() -> None:
    with db_session() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS schedule_versions (
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, format TEXT NOT NULL,
          checksum TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activities (
          id INTEGER PRIMARY KEY, version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          source_key TEXT NOT NULL, external_id TEXT NOT NULL, name TEXT NOT NULL,
          wbs TEXT, discipline TEXT, location TEXT, planned_start TEXT, planned_finish TEXT,
          actual_start TEXT, actual_finish TEXT, status TEXT,
          UNIQUE(version_id, external_id)
        );
        CREATE TABLE IF NOT EXISTS relationships (
          id INTEGER PRIMARY KEY, version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          predecessor TEXT, successor TEXT, kind TEXT, lag TEXT
        );
        CREATE TABLE IF NOT EXISTS reports (
          id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          source_kind TEXT NOT NULL, filename TEXT, content TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(id),
          source_row INTEGER, text TEXT NOT NULL, kind TEXT NOT NULL,
          event_date TEXT, discipline TEXT, location TEXT,
          status TEXT NOT NULL, candidates TEXT NOT NULL, warnings TEXT NOT NULL,
          selected_activity TEXT, decision_reason TEXT, decided_at TEXT,
          analysis_mode TEXT NOT NULL DEFAULT 'rules', model_name TEXT,
          clarification_question TEXT, clarification_answer TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
          action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exports (
          id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          content TEXT NOT NULL, manifest TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity_embeddings (
          version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          model TEXT NOT NULL, activity_id TEXT NOT NULL, vector TEXT NOT NULL,
          PRIMARY KEY (version_id, model, activity_id)
        );
        CREATE TABLE IF NOT EXISTS capture_assets (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, filename TEXT NOT NULL,
          checksum TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_requests (
          id TEXT PRIMARY KEY, payload_checksum TEXT NOT NULL,
          report_id TEXT NOT NULL REFERENCES reports(id)
        );
        CREATE TABLE IF NOT EXISTS report_similarities (
          report_id TEXT NOT NULL REFERENCES reports(id), related_id TEXT NOT NULL REFERENCES reports(id),
          similarity REAL NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(report_id,related_id)
        );
        CREATE TABLE IF NOT EXISTS processing_runs (
          id TEXT PRIMARY KEY, report_id TEXT REFERENCES reports(id), mode TEXT,
          elapsed_ms REAL NOT NULL, queue_ms REAL NOT NULL, failed INTEGER NOT NULL,
          error_type TEXT, model_calls TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,payload TEXT NOT NULL,checksum TEXT NOT NULL,status TEXT NOT NULL,error_type TEXT,report_id TEXT,created_at TEXT NOT NULL);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        for name, definition in (("analysis_mode", "TEXT NOT NULL DEFAULT 'rules'"),
                                 ("model_name", "TEXT"), ("clarification_question", "TEXT"),
                                 ("clarification_answer", "TEXT"), ("checks", "TEXT NOT NULL DEFAULT '[]'"),
                                 ("routing", "TEXT NOT NULL DEFAULT '{}'"), ("duplicate_of_event", "TEXT"), ("verification", "TEXT NOT NULL DEFAULT '{}'")):
            if name not in columns:
                db.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")
        report_columns = {row["name"] for row in db.execute("PRAGMA table_info(reports)")}
        if "capture_asset_id" not in report_columns:
            db.execute("ALTER TABLE reports ADD COLUMN capture_asset_id TEXT REFERENCES capture_assets(id)")
        for name, definition in (("fingerprint", "TEXT"), ("normalized_text", "TEXT"), ("identity_context", "TEXT"),
                                 ("duplicate_of", "TEXT REFERENCES reports(id)"), ("duplicate_group_id", "TEXT"), ("input_rows", "TEXT")):
            if name not in report_columns:
                db.execute(f"ALTER TABLE reports ADD COLUMN {name} {definition}")
        db.execute("UPDATE reports SET duplicate_group_id=id WHERE duplicate_group_id IS NULL")
        db.executescript("""
          CREATE INDEX IF NOT EXISTS reports_fingerprint_idx ON reports(version_id,fingerprint);
          CREATE INDEX IF NOT EXISTS reports_group_idx ON reports(duplicate_group_id);
          CREATE INDEX IF NOT EXISTS events_activity_idx ON events(selected_activity,kind,event_date,status);
          CREATE INDEX IF NOT EXISTS events_history_idx ON events(discipline,status,event_date);
          CREATE INDEX IF NOT EXISTS events_report_idx ON events(report_id);
        """)
        auth.init_auth(db)
        export_columns={row["name"] for row in db.execute("PRAGMA table_info(exports)")}
        for field in ("xer_content","changeset"):
            if field not in export_columns: db.execute(f"ALTER TABLE exports ADD COLUMN {field} TEXT")
    if DB_PATH.exists(): DB_PATH.chmod(0o600)


def latest_version(db: sqlite3.Connection) -> sqlite3.Row | None:
    if auth.project_context.get():
        return db.execute("SELECT * FROM schedule_versions WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",(auth.project_context.get(),)).fetchone()
    return db.execute("SELECT * FROM schedule_versions ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()


def activities_for(db: sqlite3.Connection, version_id: str) -> list[dict]:
    return [dict(row) for row in db.execute(
        "SELECT * FROM activities WHERE version_id=? ORDER BY external_id", (version_id,)
    )]


def relationships_for(db: sqlite3.Connection, version_id: str) -> list[dict]:
    # The importer resolves TASKPRED task_id references exactly once. An external
    # numeric activity code must never be remapped as another task's internal ID.
    return [dict(row) for row in db.execute(
        "SELECT predecessor, successor, kind, lag FROM relationships WHERE version_id=?", (version_id,)
    )]


def embedding_index(version_id: str, activities: list[dict], client: OpenAIClient) -> dict[str, list[float]]:
    with db_session() as db:
        stored = {row["activity_id"]: json.loads(row["vector"]) for row in db.execute(
            "SELECT activity_id, vector FROM activity_embeddings WHERE version_id=? AND model=?",
            (version_id, client.embedding_model))}
    missing = [activity for activity in activities if activity["external_id"] not in stored]
    for start in range(0, len(missing), 64):
        batch = missing[start:start + 64]
        vectors = client.embed([activity_card(activity) for activity in batch])
        with db_session() as db:
            db.executemany("INSERT OR REPLACE INTO activity_embeddings VALUES (?,?,?,?)",
                           [(version_id, client.embedding_model, activity["external_id"], json.dumps(vector))
                            for activity, vector in zip(batch, vectors)])
        stored.update({activity["external_id"]: vector for activity, vector in zip(batch, vectors)})
    return stored


def dependency_warnings(event: dict, candidate_id: str, activities: list[dict],
                        relationships: list[dict]) -> list[str]:
    if event["kind"] != "actual_start" or not candidate_id:
        return []
    by_id = {activity["external_id"]: activity for activity in activities}
    warnings = []
    for relation in relationships:
        if relation["successor"] != candidate_id or relation["kind"] not in {"PR_FS", "FS"}:
            continue
        predecessor = by_id.get(relation["predecessor"])
        if not predecessor:
            continue
        finish = predecessor.get("actual_finish") or ""
        if not finish:
            warnings.append(f"Predecessor {relation['predecessor']} has no actual finish")
        elif event.get("event_date") and finish[:10] > event["event_date"]:
            warnings.append(f"Starts before predecessor {relation['predecessor']} finished")
    return warnings


def event_record(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["candidates"] = json.loads(value["candidates"])
    value["warnings"] = json.loads(value["warnings"])
    value["checks"] = json.loads(value.get("checks") or "[]")
    value["routing"] = json.loads(value.get("routing") or "{}")
    value["verification"] = json.loads(value.get("verification") or "{}")
    return value


def reviewed_activities(db, version_id):
    activities = activities_for(db, version_id)
    by_id = {activity["external_id"]: activity for activity in activities}
    for event in db.execute("""SELECT e.selected_activity,e.kind,e.event_date FROM events e JOIN reports r ON r.id=e.report_id
            WHERE r.version_id=? AND e.status IN ('approved','exported') ORDER BY e.decided_at,e.rowid""", (version_id,)):
        if event["selected_activity"] in by_id and event["kind"] in {"actual_start", "actual_finish"}:
            by_id[event["selected_activity"]][event["kind"]] = event["event_date"]
    return activities


def report_result(db, report_id, **extra):
    report = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    root = report["duplicate_of"] or report_id
    events = [event_record(row) for row in db.execute("SELECT * FROM events WHERE report_id=? ORDER BY rowid", (root,))]
    return {"report_id": report_id, "schedule_version": report["version_id"], "events": events,
            "duplicate": bool(report["duplicate_of"]), "duplicate_of": report["duplicate_of"],
            "duplicate_group_id": report["duplicate_group_id"], **extra}


def import_schedule(filename: str, content: str) -> dict:
    if not filename or not content:
        raise ValueError("Choose a non-empty schedule file")
    activities, relationships, file_format = parse_schedule(content, filename)
    version_id = uid("sch")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with db_session() as db:
        db.execute("INSERT INTO schedule_versions (id,filename,format,checksum,content,created_at,project_id) VALUES (?,?,?,?,?,?,?)",
                   (version_id, filename, file_format, checksum, content, now(),auth.project_context.get() or "prj_default"))
        db.executemany("""INSERT INTO activities
          (version_id,source_key,external_id,name,wbs,discipline,location,
           planned_start,planned_finish,actual_start,actual_finish,status)
          VALUES (:version_id,:source_key,:external_id,:name,:wbs,:discipline,:location,
                  :planned_start,:planned_finish,:actual_start,:actual_finish,:status)""",
          [dict(row, version_id=version_id) for row in activities])
        db.executemany("""INSERT INTO relationships
          (version_id,predecessor,successor,kind,lag) VALUES (?,?,?,?,?)""",
          [(version_id, r["predecessor"], r["successor"], r["kind"], r["lag"]) for r in relationships])
    return {"id": version_id, "filename": filename, "format": file_format,
            "activity_count": len(activities), "relationship_count": len(relationships), "checksum": checksum}


def _report_rows(payload: dict) -> list[dict]:
    kind = payload.get("source_kind", "text")
    if payload.get("capture_asset_id"):
        with db_session() as db:
            asset = db.execute("SELECT * FROM capture_assets WHERE id=?", (payload["capture_asset_id"],)).fetchone()
        if not asset or asset["kind"] != kind or kind not in {"document", "voice"}:
            raise ValueError("The capture source could not be found")
        if auth.project_context.get() and asset["project_id"] != auth.project_context.get():
            raise auth.AccessError("Capture source not found in this project",404)
        metadata = json.loads(asset["metadata"])
        originals = metadata["pages"] if kind == "document" else [{"text": metadata["text"], "source_row": None, "warnings": metadata["warnings"]}]
        reviewed = payload.get("reviewed_pages") if kind == "document" else [{"text": payload.get("content", "")}]
        if not isinstance(reviewed, list) or len(reviewed) != len(originals):
            raise ValueError("Review each extracted page before submitting the document")
        rows = []
        for original, correction in zip(originals, reviewed):
            text = correction.get("text") if isinstance(correction, dict) else None
            if not isinstance(text, str) or len(text) > 12000:
                raise ValueError("Each reviewed page must contain at most 12,000 characters")
            if text.strip():
                rows.append({"text": text.strip(), "source_row": original["source_row"],
                             "source_warnings": original.get("warnings", []),
                             "event_date": payload.get("event_date") or "",
                             "discipline": payload.get("discipline") or "", "location": payload.get("location") or ""})
        return rows
    if kind == "document":
        rows = document_rows(payload.get("filename", ""), payload.get("content", ""))
        return [dict(row, event_date=(payload.get("event_date") or "").strip(),
                     discipline=(payload.get("discipline") or "").strip(),
                     location=(payload.get("location") or "").strip()) for row in rows]
    if kind == "spreadsheet":
        reader = csv.DictReader(io.StringIO(payload.get("content", "")))
        if not reader.fieldnames or not ({"report_text", "text", "description"} & set(reader.fieldnames)):
            raise ValueError("Spreadsheet CSV needs report_text, text, or description column")
        rows = []
        for number, row in enumerate(reader, 2):
            text = (row.get("report_text") or row.get("text") or row.get("description") or "").strip()
            if text:
                rows.append({"text": text, "source_row": number,
                             "event_date": (row.get("event_date") or payload.get("event_date") or "").strip(),
                             "discipline": (row.get("discipline") or payload.get("discipline") or "").strip(),
                             "location": (row.get("location") or payload.get("location") or "").strip()})
        return rows
    if kind != "text":
        raise ValueError("Source kind must be text, spreadsheet, or document")
    return [{"text": payload.get("content", "").strip(), "source_row": None,
             "event_date": payload.get("event_date", ""),
             "discipline": payload.get("discipline", ""),
             "location": payload.get("location", "")}]


def existing_report_request(db: sqlite3.Connection, request_id: str, checksum: str) -> dict | None:
    receipt = db.execute("SELECT * FROM report_requests WHERE id=?", (request_id,)).fetchone()
    if not receipt:
        return None
    if auth.project_context.get():
        project=db.execute("SELECT v.project_id FROM reports r JOIN schedule_versions v ON v.id=r.version_id WHERE r.id=?",(receipt["report_id"],)).fetchone()
        if not project or project["project_id"]!=auth.project_context.get(): raise auth.AccessError("Report request not found",404)
    if receipt["payload_checksum"] != checksum:
        raise ScheduleConflict("This saved report was changed after submission. Save a new report instead.")
    return report_result(db, receipt["report_id"], replayed=True)


def save_capture(kind: str, payload: dict, metadata: dict) -> dict:
    filename = Path(payload.get("filename", "report")).name
    suffix = Path(filename).suffix.lower()
    raw = payload["content"].encode("utf-8") if suffix in {".txt", ".eml"} else decode_file(payload["content"])
    if len(raw) > 10_000_000:
        raise ValueError("Capture files must be 10 MB or smaller")
    asset_id = uid("cap")
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    CAPTURE_DIR.chmod(0o700)
    target = CAPTURE_DIR / asset_id
    target.write_bytes(raw)
    target.chmod(0o600)
    try:
        with db_session() as db:
            db.execute("INSERT INTO capture_assets (id,kind,filename,checksum,metadata,created_at,project_id) VALUES (?,?,?,?,?,?,?)",
                       (asset_id, kind, filename, hashlib.sha256(raw).hexdigest(), json.dumps(metadata), now(),auth.project_context.get() or "prj_default"))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"capture_asset_id": asset_id, "filename": filename, "original_url": f"/api/captures/{asset_id}/original", **metadata}


def process_capture(kind,payload,asset_id=None):
    options={key:payload.get(key) for key in ("handwriting","language")}
    receipt=save_capture(kind,payload,{"verification":"needs_review","processing_status":"received","capture_options":options}) if not asset_id else {"capture_asset_id":asset_id,"filename":payload["filename"],"original_url":f"/api/captures/{asset_id}/original"}
    try:
        metadata={"pages":extract_document(payload["filename"],payload["content"],bool(payload.get("handwriting")))} if kind=="document" else transcribe_audio(payload["filename"],payload["content"],payload.get("language") or "")
        metadata.update(verification="needs_review",processing_status="extracted",capture_options=options)
    except Exception as exc:
        metadata={"verification":"needs_review","processing_status":"needs_retry","error_type":type(exc).__name__,"capture_options":options}
        with db_session() as db: db.execute("UPDATE capture_assets SET metadata=? WHERE id=?",(json.dumps(metadata),receipt["capture_asset_id"]))
        exc.capture_asset_id=receipt["capture_asset_id"]
        raise
    with db_session() as db: db.execute("UPDATE capture_assets SET metadata=? WHERE id=?",(json.dumps(metadata),receipt["capture_asset_id"]))
    return {**receipt,**metadata}


def analytics_payload(payload: dict | None = None) -> dict:
    payload = payload or {}
    with db_session() as db:
        version = latest_version(db)
        if not version:
            return {"available": False, "reason": "Import a schedule to explore forecast scenarios.", "activities": []}
        activities = activities_for(db, version["id"])
        relationships = relationships_for(db, version["id"])
        events = [dict(row) for row in db.execute("""SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id
                    WHERE r.version_id=? ORDER BY e.decided_at, e.rowid""", (version["id"],))]
    result = schedule_analytics(activities, relationships, events,
                               payload.get("as_of") or datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(),
                               float(payload.get("duration_factor", 1)))
    return {"schedule_version": version["id"], **result}


def submit_report(payload: dict) -> dict:
    payload=dict(payload)
    submission_id=payload.get("client_request_id") or uid("sub")
    payload["client_request_id"]=submission_id
    if not isinstance(submission_id,str) or len(submission_id)>100: raise ValueError("Invalid request ID")
    project=auth.project_context.get() or "prj_default"
    checksum=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("SELECT * FROM submissions WHERE id=?",(submission_id,)).fetchone()
        if old and (old["project_id"]!=project or old["checksum"]!=checksum): raise ScheduleConflict("Saved submission identity changed; create a new request")
        db.execute("INSERT OR IGNORE INTO submissions VALUES (?,?,?,?,?,?,?,?)",(submission_id,project,json.dumps(payload),checksum,"received","",None,now()))
    started, result, error_type = time.perf_counter(), None, ""
    calls = []
    token = active_calls.set(calls)
    acquired = started
    try:
        with _report_lock:
            acquired = time.perf_counter()
            result = _submit_report(payload)
            return result
    except Exception as exc:
        error_type = type(exc).__name__
        exc.submission_id=submission_id
        raise
    finally:
        active_calls.reset(token)
        try:
            with db_session() as db:
                db.execute("UPDATE submissions SET status=?,error_type=?,report_id=? WHERE id=?",("failed" if error_type else "complete",error_type,result.get("report_id") if result else None,submission_id))
                parent=payload.get("fallback_for") or payload.get("supersedes_submission")
                if result and parent:
                    db.execute("UPDATE submissions SET status='complete',report_id=? WHERE id=? AND project_id=?",(result["report_id"],parent,project))
                db.execute("INSERT INTO processing_runs (id,report_id,mode,elapsed_ms,queue_ms,failed,error_type,model_calls,created_at,project_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (uid("run"), result.get("report_id") if result else None, payload.get("analysis_mode", "rules"),
                            round((time.perf_counter()-started)*1000, 2), round((acquired-started)*1000, 2),
                            int(bool(error_type)), error_type, json.dumps(calls), now(),auth.project_context.get() or "prj_default"))
        except sqlite3.Error:
            # A telemetry write must not turn a committed report into a failed receipt.
            pass


def _submit_report(payload: dict) -> dict:
    load_local_env()
    request_id = payload.get("client_request_id", "")
    if not isinstance(request_id, str) or len(request_id) > 100:
        raise ValueError("Invalid client request ID")
    checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if request_id:
        with db_session() as db:
            previous = existing_report_request(db, request_id, checksum)
            if previous:
                return previous
    rows = _report_rows(payload)
    if not rows or not any(row["text"] for row in rows):
        raise ValueError("Report has no usable text")
    analysis_mode = payload.get("analysis_mode", "rules")
    if analysis_mode not in {"rules", "ai"}:
        raise ValueError("Analysis mode must be rules or ai")
    for row in rows:
        if row["event_date"]:
            date.fromisoformat(row["event_date"])
    if analysis_mode == "ai" and (len(rows) > 5 or sum(len(row["text"]) for row in rows) > 12_000):
        raise ValueError("AI input is limited to five rows and 12,000 characters per report")
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        version = latest_version(db)
        if not version:
            raise ValueError("Import a schedule before submitting reports")
        if payload.get("schedule_version") and payload["schedule_version"] != version["id"]:
            raise ScheduleConflict("The schedule changed. Review the saved report against the new import before submitting it.")
        activities = reviewed_activities(db, version["id"])
        relationships = relationships_for(db, version["id"])
        version_id = version["id"]
        fingerprint, normalized_text, identity_context = identity(rows, now()[:10])
        duplicate = db.execute("SELECT id FROM reports WHERE version_id=? AND fingerprint=? AND duplicate_of IS NULL ORDER BY rowid LIMIT 1",
                               (version_id, fingerprint)).fetchone()
        if duplicate:
            report_id = uid("rpt")
            db.execute("""INSERT INTO reports (id,version_id,source_kind,filename,content,created_at,capture_asset_id,
                          fingerprint,normalized_text,identity_context,duplicate_of,duplicate_group_id,input_rows) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (report_id, version_id, payload.get("source_kind", "text"), payload.get("filename", ""),
                        "\n\n".join(row["text"] for row in rows), now(), payload.get("capture_asset_id") or None,
                        fingerprint, normalized_text, identity_context, duplicate["id"], duplicate["id"],json.dumps(rows)))
            if request_id: db.execute("INSERT INTO report_requests VALUES (?,?,?)", (request_id, checksum, report_id))
            return report_result(db, report_id, analysis_mode=analysis_mode)
        possible_duplicates = similar_reports(normalized_text, identity_context, [dict(row) for row in db.execute(
            "SELECT id,normalized_text,identity_context FROM reports WHERE version_id=? AND duplicate_of IS NULL ORDER BY rowid DESC LIMIT 200", (version_id,))])
    client = None
    vectors = None
    if analysis_mode == "ai":
        status = ai_status()
        if not status["available"]:
            raise AiUnavailable(status["message"])
        client = model_client()
        vectors = embedding_index(version_id, activities, client)
    output = []
    for row in rows:
        if analysis_mode == "ai":
            events = analyze_report(row["text"], row["event_date"], row["discipline"], row["location"],
                                    activities, relationships, vectors, client, status["reranker"])
        else:
            events = []
            for event in extract_events(row["text"], row["event_date"], row["discipline"], row["location"]):
                candidates = rank_activities(event, activities)
                state, warnings = route_event(event, candidates)
                events.append({**event, "candidates": candidates, "status": state, "warnings": warnings,
                               "clarification_question": ""})
        for event in events:
            candidates = event["candidates"]
            warnings = list(event["warnings"])
            warnings.extend(row.get("source_warnings", []))
            checks = actual_checks(event, candidates[0]["activity_id"] if candidates else "", activities, relationships,
                                   datetime.now(ZoneInfo("Asia/Kolkata")).date())
            warnings.extend(item["message"] for item in checks if item["severity"] != "info")
            if possible_duplicates: warnings.append("Possible duplicate report: compare the grouped source evidence before approval")
            routing = routing_details(candidates, pipeline_for(client, status["reranker"] if client else "llm"),payload.get("source_kind","text"),event.get("discipline",""))
            if routing["score"] < routing["min_score"]: warnings.append("No reliable activity match")
            if len(candidates) > 1 and routing["margin"] < routing["min_margin"]: warnings.append("Several activities are plausible")
            blocking = [message for message in warnings if message != "AI suggestion requires planner confirmation"]
            staged = not blocking and (analysis_mode == "rules" or routing["calibrated"])
            output.append(dict(event, source_row=row["source_row"],
                               status="staged" if staged else "needs_review", warnings=list(dict.fromkeys(warnings)), checks=checks, routing=routing))
    source_content = (payload.get("content", "") if payload.get("source_kind") != "document"
                      else "\n\n".join(row["text"] for row in rows))
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        if request_id:
            previous = existing_report_request(db, request_id, checksum)
            if previous:
                return previous
        if latest_version(db)["id"] != version_id:
            raise ScheduleConflict("The schedule changed during analysis. Review the report against the new import and retry.")
        pending = [event_record(row) for row in db.execute("SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? AND e.status IN ('staged','needs_review')",(version_id,))]
        for event in output:
            checks = competing_claims(event, [*pending,*[other for other in output if other is not event]], event["candidates"][0]["activity_id"] if event["candidates"] else "")
            event["checks"].extend(checks)
            event["warnings"] = list(dict.fromkeys([*event["warnings"],*[item["message"] for item in checks]]))
            if checks: event["status"] = "needs_review"
        report_id = uid("rpt")
        db.execute("""INSERT INTO reports (id,version_id,source_kind,filename,content,created_at,capture_asset_id,
                      fingerprint,normalized_text,identity_context,duplicate_group_id,input_rows) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (report_id, version_id, payload.get("source_kind", "text"),
                    payload.get("filename", ""), source_content, now(), payload.get("capture_asset_id") or None,
                    fingerprint, normalized_text, identity_context, report_id,json.dumps(rows)))
        for similar in possible_duplicates:
            db.execute("INSERT INTO report_similarities VALUES (?,?,?,?)", (report_id, similar["report_id"], similar["similarity"], similar["reason"]))
        for event in output:
            event_id = uid("evt")
            db.execute("""INSERT INTO events
              (id,report_id,source_row,text,kind,event_date,discipline,location,status,candidates,warnings,
               analysis_mode,model_name,clarification_question,checks,routing)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (event_id, report_id, event["source_row"], event["text"], event["kind"],
               event["event_date"], event["discipline"], event["location"], event["status"],
               json.dumps(event["candidates"]), json.dumps(event["warnings"]), analysis_mode,
               client.model if client else "", event.get("clarification_question", ""), json.dumps(event["checks"]), json.dumps(event["routing"])))
            event["id"] = event_id
            verification={"source":"confirmed_by_submitter" if payload.get("source_reviewed") else "original_text", "analysis":"ai_needs_planner_review" if client else "rules_need_planner_review"}
            db.execute("UPDATE events SET verification=? WHERE id=?",(json.dumps(verification),event_id))
            event["verification"]=verification
        if request_id:
            db.execute("INSERT INTO report_requests VALUES (?,?,?)", (request_id, checksum, report_id))
        return {"report_id": report_id, "schedule_version": version_id,
                "analysis_mode": analysis_mode, "events": output, "duplicate": False, "possible_duplicates": possible_duplicates}


def clarify_event(event_id: str, answer: str) -> dict:
    calls, started, failure, report_id = [], time.perf_counter(), "", None
    token = active_calls.set(calls)
    try:
        result = _clarify_event(event_id, answer)
        report_id = result.pop("report_id")
        return result
    except Exception as exc:
        failure = type(exc).__name__
        raise
    finally:
        active_calls.reset(token)
        try:
            with db_session() as db:
                db.execute("INSERT INTO processing_runs (id,report_id,mode,elapsed_ms,queue_ms,failed,error_type,model_calls,created_at,project_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (uid("run"), report_id, "clarification", round((time.perf_counter()-started)*1000, 2),
                            0, int(bool(failure)), failure, json.dumps(calls), now(),auth.project_context.get() or "prj_default"))
        except sqlite3.Error:
            pass


def _clarify_event(event_id: str, answer: str) -> dict:
    answer = answer.strip()
    if not answer or len(answer) > 400:
        raise ValueError("Clarification must be between 1 and 400 characters")
    with db_session() as db:
        row = db.execute("""SELECT e.*, r.version_id,r.source_kind FROM events e JOIN reports r ON r.id=e.report_id
                            WHERE e.id=?""", (event_id,)).fetchone()
        if not row:
            raise LookupError("Event not found")
        if row["analysis_mode"] != "ai" or row["status"] not in {"needs_review", "staged"}:
            raise ValueError("Only pending AI suggestions can be clarified")
        if latest_version(db)["id"] != row["version_id"]:
            raise ScheduleConflict("Re-submit this source against the current schedule before refining it")
        activities = reviewed_activities(db, row["version_id"])
        relationships = relationships_for(db, row["version_id"])
        version_id = row["version_id"]
        event = dict(row)
    status = ai_status()
    if not status["available"]:
        raise AiUnavailable(status["message"])
    client = model_client()
    vectors = embedding_index(version_id, activities, client)
    candidates, ambiguous, question = rank_event(event, activities, relationships, vectors, client,
                                                 status["reranker"], clarification=answer)
    previous_checks = {item["message"] for item in json.loads(event["checks"])}
    warnings = [warning for warning in json.loads(event["warnings"])
                if warning not in previous_checks | {"Several activities are plausible", "No reliable activity match"}]
    if ambiguous:
        warnings.append("Several activities are plausible")
    routing = routing_details(candidates, pipeline_for(client, status["reranker"]),event["source_kind"],event.get("discipline",""))
    if routing["score"] < routing["min_score"]: warnings.append("No reliable activity match")
    if len(candidates) > 1 and routing["margin"] < routing["min_margin"]: warnings.append("Several activities are plausible")
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        if latest_version(db)["id"] != version_id:
            raise ScheduleConflict("The schedule changed during refinement; re-submit the source")
        checks = actual_checks(event, candidates[0]["activity_id"] if candidates else "",
                               reviewed_activities(db, version_id), relationships_for(db, version_id),
                               datetime.now(ZoneInfo("Asia/Kolkata")).date())
        checks.extend(pending_checks(db,event,candidates[0]["activity_id"] if candidates else "",event["event_date"]))
        warnings.extend(item["message"] for item in checks if item["severity"] != "info")
        warnings = list(dict.fromkeys(warnings))
        state = "staged" if routing["calibrated"] and not [w for w in warnings if w != "AI suggestion requires planner confirmation"] else "needs_review"
        changed = db.execute("""UPDATE events SET candidates=?, warnings=?, clarification_question=?, clarification_answer=?, model_name=?,checks=?,routing=?,status=?
                      WHERE id=? AND status IN ('needs_review','staged')""",
                   (json.dumps(candidates), json.dumps(warnings), question if ambiguous else "", answer,
                    client.model, json.dumps(checks), json.dumps(routing), state, event_id))
        if changed.rowcount != 1:
            raise ValueError("This event already has a decision")
        db.execute("INSERT INTO audit (event_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                   (event_id, "clarify", (auth.user_context.get() or {}).get("name") or "Supervisor", json.dumps({"answer": answer,"user_id":(auth.user_context.get() or {}).get("id"),
                    "candidate_ids": [candidate["activity_id"] for candidate in candidates]}), now()))
    return {"id": event_id, "report_id": event["report_id"], "candidates": candidates, "warnings": warnings, "checks": checks, "routing": routing,
            "clarification_question": question if ambiguous else "", "clarification_answer": answer}


def decide_event(event_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action not in {"approve", "reject", "record"}:
        raise ValueError("Action must be approve, reject, or record")
    reason = (payload.get("reason") or "").strip()
    actor = (auth.user_context.get() or {}).get("name") or (payload.get("actor") or "Planner").strip()[:80]
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        event = db.execute("""SELECT e.*, r.version_id FROM events e
            JOIN reports r ON r.id=e.report_id WHERE e.id=?""", (event_id,)).fetchone()
        if not event:
            raise LookupError("Event not found")
        if event["status"] in {"approved", "rejected", "recorded", "exported", "duplicate"}:
            raise ValueError("This event already has a decision")
        if action != "reject" and latest_version(db)["id"] != event["version_id"]:
            raise ScheduleConflict("This event belongs to an older schedule. Re-submit its source against the current import.")
        activity_id = (payload.get("activity_id") or "").strip()
        event_date = (payload.get("event_date",event["event_date"]) or "").strip()
        if action == "approve":
            if event["kind"] not in {"actual_start", "actual_finish"}:
                raise ValueError("Only actual start and finish events can update the schedule")
            if not activity_id or not db.execute("SELECT 1 FROM activities WHERE version_id=? AND external_id=?",
                                                 (event["version_id"], activity_id)).fetchone():
                raise ValueError("Choose an activity from the imported schedule")
            if not event_date:
                raise ValueError("Enter the actual event date")
            date.fromisoformat(event_date)
            if date.fromisoformat(event_date) > datetime.now(ZoneInfo("Asia/Kolkata")).date():
                raise ValueError("An actual event date cannot be in the future")
            checks = actual_checks({"kind": event["kind"], "event_date": event_date}, activity_id,
                                   reviewed_activities(db, event["version_id"]), relationships_for(db, event["version_id"]),
                                   datetime.now(ZoneInfo("Asia/Kolkata")).date())
            checks.extend(pending_checks(db,dict(event),activity_id,event_date))
            errors = [item["message"] for item in checks if item["severity"] == "error"]
            if errors:
                raise ValueError("; ".join(errors))
            if any(item["severity"] == "warning" for item in checks) and not reason:
                raise ValueError("Add a decision note acknowledging the dependency or missing-date warnings")
            duplicate = next((item for item in checks if item["code"] == "duplicate_actual"), None)
            status = "duplicate" if duplicate else "approved"
            prior = db.execute("""SELECT e.id FROM events e JOIN reports r ON r.id=e.report_id
                WHERE r.version_id=? AND e.selected_activity=? AND e.kind=? AND e.event_date=?
                AND e.status IN ('approved','exported') ORDER BY e.decided_at,e.id LIMIT 1""",
                (event["version_id"], activity_id, event["kind"], event_date)).fetchone()
            db.execute("UPDATE events SET checks=?,duplicate_of_event=? WHERE id=?",
                       (json.dumps(checks), prior["id"] if duplicate and prior else None, event_id))

        elif action == "record":
            if activity_id and not db.execute("SELECT 1 FROM activities WHERE version_id=? AND external_id=?",
                                              (event["version_id"], activity_id)).fetchone():
                raise ValueError("Choose an activity from the imported schedule")
            if event_date:
                date.fromisoformat(event_date)
            checks = actual_checks({**dict(event),"event_date":event_date},activity_id,
                                   reviewed_activities(db,event["version_id"]),relationships_for(db,event["version_id"]),
                                   datetime.now(ZoneInfo("Asia/Kolkata")).date())
            checks.extend(pending_checks(db,dict(event),activity_id,event_date))
            if any(item["severity"] == "warning" for item in checks) and not reason:
                raise ValueError("Add a decision note explaining the conflicting progress claim")
            db.execute("UPDATE events SET checks=? WHERE id=?",(json.dumps(checks),event_id))
            status = "recorded"
        else:
            status = "rejected"
            activity_id = ""
        db.execute("""UPDATE events SET status=?, selected_activity=?, event_date=?,
                  decision_reason=?, decided_at=? WHERE id=?""",
                  (status, activity_id, event_date, reason, now(), event_id))
        db.execute("INSERT INTO audit (event_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                   (event_id, "consolidate" if status == "duplicate" else action, actor, json.dumps({"activity_id": activity_id, "event_date": event_date, "reason": reason,"user_id":(auth.user_context.get() or {}).get("id")}), now()))
        return {"id": event_id, "status": status, "activity_id": activity_id, "event_date": event_date}


def build_export() -> dict:
    with db_session() as db:
        db.execute("BEGIN IMMEDIATE")
        version = latest_version(db)
        if not version:
            raise ValueError("Import a schedule first")
        rows = db.execute("""SELECT e.*, r.version_id FROM events e JOIN reports r ON r.id=e.report_id
            WHERE r.version_id=? AND e.status='approved' ORDER BY e.decided_at, e.id""", (version["id"],)).fetchall()
        if not rows:
            raise ValueError("There are no approved events to export")
        effective = reviewed_activities(db, version["id"])
        relationships = relationships_for(db, version["id"])
        seen = {(row["selected_activity"], row["kind"], row["event_date"]): row["id"] for row in db.execute(
            "SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? AND e.status='exported'", (version["id"],))}
        unique, consolidated = [], []
        baseline = {a["external_id"]: a for a in activities_for(db, version["id"])}
        for row in rows:
            if row["kind"] not in {"actual_start", "actual_finish"}:
                raise ValueError("Export contains a non-actual event")
            checks = actual_checks(dict(row), row["selected_activity"], effective, relationships,
                                   datetime.now(ZoneInfo("Asia/Kolkata")).date())
            errors = [item["message"] for item in checks if item["severity"] == "error"]
            if errors: raise ValueError("Export blocked: " + "; ".join(errors))
            if any(item["severity"] == "warning" for item in checks) and not row["decision_reason"]:
                raise ValueError("Review dependency warnings before exporting " + row["id"])
            key = (row["selected_activity"], row["kind"], row["event_date"])
            imported = (baseline.get(row["selected_activity"], {}).get(row["kind"]) or "")[:10]
            if imported and imported != row["event_date"]:
                raise ValueError("Export blocked: this actual conflicts with the imported schedule")
            if key in seen or imported == row["event_date"]:
                db.execute("UPDATE events SET status='duplicate',duplicate_of_event=? WHERE id=?", (seen.get(key), row["id"]))
                db.execute("INSERT INTO audit (event_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                           (row["id"], "consolidate", "Export validation", json.dumps({"duplicate_of": seen.get(key), "already_in_import": imported == row["event_date"]}), now()))
                consolidated.append(row["id"])
            else:
                seen[key] = row["id"]; unique.append(row)
        rows = unique
        if not rows:
            return {"id": None, "manifest": {"row_count": 0}, "download": None,
                    "message": "These actuals were already recorded. Duplicate claims were grouped; no new export was created.", "consolidated_event_ids": consolidated}
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["schedule_version", "activity_id", "event_kind", "actual_date", "discipline",
                         "source_report", "source_row", "event_id", "approved_at"])
        for row in rows:
            writer.writerow([version["id"], row["selected_activity"], row["kind"], row["event_date"],
                             row["discipline"], row["report_id"], row["source_row"] or "", row["id"], row["decided_at"]])
        content = stream.getvalue()
        cumulative=[dict(row) for row in db.execute("SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? AND e.status IN ('approved','exported') AND e.kind IN ('actual_start','actual_finish') ORDER BY e.decided_at,e.id",(version["id"],))]
        xer_content,changeset=progress_output(version["content"],version["filename"],cumulative)
        export_id = uid("exp")
        manifest = {"schedule_version": version["id"], "source_checksum": version["checksum"],
                    "event_ids": [row["id"] for row in rows], "row_count": len(rows),
                    "output_checksum": hashlib.sha256(content.encode()).hexdigest(),
                    "format": "csv", "created_at": now()}
        manifest.update(xer_available=bool(xer_content),round_trip_verified=changeset["round_trip_verified"],oracle_import_verified=False)
        db.execute("INSERT INTO exports (id,version_id,content,manifest,created_at) VALUES (?,?,?,?,?)",
                   (export_id, version["id"], content, json.dumps(manifest), now()))
        db.execute("UPDATE exports SET xer_content=?,changeset=? WHERE id=?",(xer_content,json.dumps(changeset),export_id))
        db.executemany("UPDATE events SET status='exported' WHERE id=?", [(row["id"],) for row in rows])
        return {"id": export_id, "manifest": manifest, "download": f"/api/exports/{export_id}.csv", "xer_download":f"/api/exports/{export_id}.xer" if xer_content else None,"changeset_download":f"/api/exports/{export_id}.json"}


def check_proposal(event_id, payload):
    with db_session() as db:
        event = db.execute("SELECT e.*,r.version_id FROM events e JOIN reports r ON r.id=e.report_id WHERE e.id=?", (event_id,)).fetchone()
        if not event: raise LookupError("Event not found")
        checks = actual_checks({**dict(event), "event_date": payload.get("event_date",event["event_date"])},
                               payload.get("activity_id", ""), reviewed_activities(db, event["version_id"]),
                               relationships_for(db, event["version_id"]), datetime.now(ZoneInfo("Asia/Kolkata")).date())
        checks.extend(pending_checks(db,dict(event),payload.get("activity_id",""),payload.get("event_date",event["event_date"])))
        if latest_version(db)["id"] != event["version_id"]:
            checks.append({"code": "stale_schedule", "severity": "error", "message": "The schedule changed; re-submit the original source against the new import"})
        return {"checks": checks, "blocked": any(item["severity"] == "error" for item in checks),
                "requires_reason": any(item["severity"] == "warning" for item in checks)}


def pending_checks(db,event,activity_id,event_date):
    pending = [event_record(row) for row in db.execute("SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? AND e.status IN ('staged','needs_review') AND e.id<>?",(event["version_id"],event["id"]))]
    return competing_claims({**event,"event_date":event_date},pending,activity_id)


def summary() -> dict:
    with db_session() as db:
        version = latest_version(db)
        if not version:
            return {"schedule": None, "counts": {}, "recent": []}
        counts = {row["status"]: row["count"] for row in db.execute("""SELECT e.status, count(*) AS count
            FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? GROUP BY e.status""", (version["id"],))}
        recent = [event_record(row) for row in db.execute("""SELECT e.*, r.capture_asset_id FROM events e JOIN reports r ON r.id=e.report_id
            WHERE r.version_id=? ORDER BY r.created_at DESC, e.rowid DESC LIMIT 8""", (version["id"],))]
        schedule = {key: version[key] for key in ("id", "filename", "format", "checksum", "created_at")}
        schedule["activity_count"] = db.execute("SELECT count(*) FROM activities WHERE version_id=?", (version["id"],)).fetchone()[0]
        return {"schedule": schedule, "counts": counts, "recent": recent}


def preview_report(payload: dict) -> dict:
    """Try a note against the bundled synthetic schedule without storing it."""
    content = payload.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Enter a field note to preview")
    if len(content) > 1000:
        raise ValueError("Preview notes must be 1,000 characters or fewer")
    event_date = payload.get("event_date", "")
    if not isinstance(event_date, str):
        raise ValueError("Preview date must be a date string")
    if event_date:
        date.fromisoformat(event_date)
    fixture = ROOT / "data" / "samples" / "pump-station.xer"
    activities, _, _ = parse_schedule(fixture.read_text(), fixture.name)
    events = []
    for event in extract_events(content.strip(), event_date, "", "")[:5]:
        candidates = rank_activities(event, activities, limit=3)
        status, warnings = route_event(event, candidates)
        events.append({**event, "status": status, "warnings": warnings,
                       "candidates": candidates})
    return {"events": events, "schedule": "Synthetic pump station", "saved": False}


class Handler(BaseHTTPRequestHandler):
    def authorize(self,path,mutating=False):
        self.context_tokens=[]
        self.session_cookie=None
        auth.valid_host(self.headers)
        if not path.startswith("/api/") or path in {"/api/health","/api/preview","/api/auth/status","/api/auth/setup","/api/auth/login"}:
            if mutating: auth.same_origin(self.headers)
            return None
        with db_session() as db:
            account=auth.session(db,self.headers)
            if mutating: auth.require_csrf(self.headers,account)
            self.context_tokens.append((auth.user_context,auth.user_context.set({"id":account["user_id"],"name":account["name"]})))
            if path not in {"/api/auth/me","/api/auth/logout","/api/auth/password","/api/projects"}:
                planner=mutating and (path.startswith("/api/schedules/") or path.endswith("/decision") or path=="/api/exports" or path=="/api/demo/load")
                headers={"X-Carrick-Project":self.headers.get("X-Carrick-Project","")}
                resource_id=re.search(r"/(cap_[a-f0-9]+|exp_[a-f0-9]+)",path)
                if not mutating and not headers.get("X-Carrick-Project") and resource_id:
                    key=resource_id.group(1)
                    query="SELECT project_id FROM capture_assets WHERE id=?" if key.startswith("cap_") else "SELECT v.project_id FROM exports e JOIN schedule_versions v ON v.id=e.version_id WHERE e.id=?"
                    resource=db.execute(query,(key,)).fetchone()
                    if not resource: raise auth.AccessError("Resource not found",404)
                    headers["X-Carrick-Project"]=resource["project_id"]
                project,role=auth.require_project(db,headers,account,planner=planner,owner=path=="/api/members")
                self.context_tokens.append((auth.project_context,auth.project_context.set(project)))
                identifier=re.search(r"/(evt_[a-f0-9]+|cap_[a-f0-9]+|exp_[a-f0-9]+)",path)
                if identifier:
                    key=identifier.group(1)
                    if key.startswith("evt_"): query="SELECT v.project_id FROM events e JOIN reports r ON r.id=e.report_id JOIN schedule_versions v ON v.id=r.version_id WHERE e.id=?"
                    elif key.startswith("cap_"): query="SELECT project_id FROM capture_assets WHERE id=?"
                    else: query="SELECT v.project_id FROM exports e JOIN schedule_versions v ON v.id=e.version_id WHERE e.id=?"
                    resource=db.execute(query,(key,)).fetchone()
                    if not resource or resource["project_id"]!=project: raise auth.AccessError("Resource not found",404)
            return account

    def clear_context(self):
        for variable,token in reversed(getattr(self,"context_tokens",[])): variable.reset(token)

    def log_message(self, format: str, *args: object) -> None:
        print("%s %s" % (self.address_string(), format % args))

    def respond(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        if getattr(self,"session_cookie",None): self.send_header("Set-Cookie",self.session_cookie)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request body must be between 1 byte and 16 MB")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            account=self.authorize(path)
            if path=="/api/auth/status":
                with db_session() as db: return self.respond(200,{"setup_required":not bool(db.execute("SELECT 1 FROM users LIMIT 1").fetchone())})
            if path in {"/api/auth/me","/api/projects"}:
                with db_session() as db:
                    projects=auth.memberships(db,account["user_id"])
                    return self.respond(200,{"user":{"id":account["user_id"],"name":account["name"],"email":account["email"]},"csrf":account["csrf"],"projects":projects})
            if path=="/api/members":
                with db_session() as db: return self.respond(200,[dict(row) for row in db.execute("SELECT u.id,u.email,u.name,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.project_id=?",(auth.project_context.get(),))])
            if path=="/api/submissions":
                with db_session() as db:
                    rows=[dict(row) for row in db.execute("SELECT * FROM submissions WHERE project_id=? AND status<>'complete' ORDER BY created_at DESC LIMIT 50",(auth.project_context.get(),))]
                    return self.respond(200,[{key:row[key] for key in ("id","status","error_type","created_at")}|{"filename":json.loads(row["payload"]).get("filename",""),"analysis_mode":json.loads(row["payload"]).get("analysis_mode","rules")} for row in rows])
            if path=="/api/captures/incomplete":
                with db_session() as db:
                    return self.respond(200,[{"capture_asset_id":row["id"],"filename":row["filename"],"kind":row["kind"],"original_url":f"/api/captures/{row['id']}/original","metadata":json.loads(row["metadata"])} for row in db.execute("SELECT * FROM capture_assets WHERE project_id=? AND json_extract(metadata,'$.processing_status') IN ('received','needs_retry') ORDER BY created_at DESC LIMIT 50",(auth.project_context.get(),))])
            match=re.fullmatch(r"/api/submissions/([A-Za-z0-9_-]{1,100})",path)
            if match:
                with db_session() as db: row=db.execute("SELECT * FROM submissions WHERE id=? AND project_id=?",(match.group(1),auth.project_context.get())).fetchone()
                if not row: return self.respond(404,{"error":"Saved submission not found"})
                return self.respond(200,{"id":row["id"],"status":row["status"],"payload":json.loads(row["payload"])})
            if path == "/api/health":
                return self.respond(200, {"status": "ok"})
            if path == "/api/ai/status":
                return self.respond(200, ai_status())
            if path == "/api/capture/status":
                return self.respond(200, capture_status())
            if path == "/api/quality/status":
                with db_session() as db:
                    return self.respond(200, quality_status(db))
            if path == "/api/analytics":
                return self.respond(200, analytics_payload())
            if path == "/api/summary":
                return self.respond(200, summary())
            if path == "/api/activities":
                with db_session() as db:
                    version = latest_version(db)
                    return self.respond(200, activities_for(db, version["id"]) if version else [])
            if path == "/api/events":
                with db_session() as db:
                    version = latest_version(db)
                    rows = db.execute("""SELECT e.*, r.capture_asset_id,r.source_kind,r.filename,r.created_at AS received_at,r.duplicate_group_id FROM events e JOIN reports r ON r.id=e.report_id
                        WHERE r.version_id=? ORDER BY r.created_at DESC, e.rowid DESC""", (version["id"],)).fetchall() if version else []
                    return self.respond(200, enrich(db, [event_record(row) for row in rows]))
            if path == "/api/history":
                params = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
                with db_session() as db:
                    version = latest_version(db)
                    return self.respond(200, query_history(db, version["id"], params, event_record) if version else
                                        {"events": [], "total": 0, "limit": 50, "offset": 0, "has_more": False})
            match = re.fullmatch(r"/api/captures/(cap_[a-f0-9]+)(/original)?", path)
            if match:
                with db_session() as db:
                    asset = db.execute("SELECT * FROM capture_assets WHERE id=?", (match.group(1),)).fetchone()
                if not asset:
                    return self.respond(404, {"error": "Capture source not found"})
                if not match.group(2):
                    return self.respond(200, {"capture_asset_id": asset["id"], "filename": asset["filename"],
                                             "kind":asset["kind"],"original_url":f"/api/captures/{asset['id']}/original","checksum": asset["checksum"], **json.loads(asset["metadata"])})
                body = (CAPTURE_DIR / asset["id"]).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                suffix=Path(asset["filename"]).suffix
                if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}",suffix): suffix=".bin"
                self.send_header("Content-Disposition", "attachment; filename=carrick-source" + suffix)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            match = re.fullmatch(r"/api/exports/(exp_[a-f0-9]+)\.(csv|xer|json)", path)
            if match:
                with db_session() as db:
                    row = db.execute("SELECT content,xer_content,changeset FROM exports WHERE id=?", (match.group(1),)).fetchone()
                if not row:
                    return self.respond(404, {"error": "Export not found"})
                selected=row[{"csv":"content","xer":"xer_content","json":"changeset"}[match.group(2)]]
                if selected is None: return self.respond(400,{"error":"This export has no native XER; download its validated change set"})
                body = selected.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", {"csv":"text/csv; charset=utf-8","xer":"application/octet-stream","json":"application/json"}[match.group(2)])
                self.send_header("Content-Disposition", f"attachment; filename=carrick-progress-{match.group(1)}.{match.group(2)}")
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            static = {"/": ("landing.html", "text/html"),
                      "/app": ("index.html", "text/html"), "/app/": ("index.html", "text/html"),
                      "/landing.js": ("landing.js", "text/javascript"),
                      "/landing.css": ("landing.css", "text/css"),
                      "/app.js": ("app.js", "text/javascript"),
                      "/auth.js": ("auth.js", "text/javascript"),
                      "/offline.js": ("offline.js", "text/javascript"),
                      "/capture.js": ("capture.js", "text/javascript"),
                      "/analytics.js": ("analytics.js", "text/javascript"),
                      "/sw.js": ("sw.js", "text/javascript"),
                      "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
                      "/styles.css": ("styles.css", "text/css"),
                      "/brand/carrick-mark.svg": ("brand/carrick-mark.svg", "image/svg+xml"),
                      "/brand/carrick-logo.svg": ("brand/carrick-logo.svg", "image/svg+xml"),
                      "/brand/field-to-schedule.svg": ("brand/field-to-schedule.svg", "image/svg+xml")}
            if path in static:
                filename, content_type = static[path]
                body = (WEB / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                if path == "/sw.js":
                    self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return self.wfile.write(body)
            return self.respond(404, {"error": "Not found"})
        except auth.AccessError as exc:
            self.respond(exc.status,{"error":str(exc),"code":"access_denied"})
        except ValueError as exc:
            self.respond(400, {"error": str(exc)})
        except Exception as exc:
            self.respond(500, {"error": str(exc)})
        finally: self.clear_context()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            account=self.authorize(path,True)
            payload = self.read_json()
            if path in {"/api/auth/setup","/api/auth/login"}:
                if path.endswith("setup") and self.client_address[0] not in {"127.0.0.1","::1"}: raise auth.AccessError("Initial setup must be performed on the host computer")
                with db_session() as db:
                    token,result=auth.setup(db,payload) if path.endswith("setup") else auth.login(db,payload,self.client_address[0])
                if not token: raise auth.AccessError("Email or password is incorrect",401)
                self.session_cookie=auth.cookie(token)
                return self.respond(200,result)
            if path=="/api/auth/logout":
                with db_session() as db: db.execute("DELETE FROM sessions WHERE token_hash=?",(account["token_hash"],))
                self.session_cookie=auth.cookie("")
                return self.respond(200,{"signed_out":True})
            if path=="/api/auth/password":
                with db_session() as db:
                    db.execute("BEGIN IMMEDIATE")
                    user=db.execute("SELECT * FROM users WHERE id=?",(account["user_id"],)).fetchone()
                    import hmac
                    if not hmac.compare_digest(auth.password_hash(payload.get("current_password"),user["password_hash"].split(":")[0]),user["password_hash"]): raise auth.AccessError("Current password is incorrect")
                    db.execute("UPDATE users SET password_hash=? WHERE id=?",(auth.password_hash(payload.get("new_password")),user["id"]))
                    db.execute("DELETE FROM sessions WHERE user_id=?",(user["id"],))
                    token,result=auth.new_session(db,{key:user[key] for key in ("id","name","email")})
                self.session_cookie=auth.cookie(token)
                return self.respond(200,result)
            if path=="/api/projects":
                name=str(payload.get("name","")).strip()[:100]
                if not name: raise ValueError("Enter a project name")
                identifier=uid("prj")
                with db_session() as db:
                    db.execute("INSERT INTO projects VALUES (?,?)",(identifier,name))
                    db.execute("INSERT INTO memberships VALUES (?,?,'owner')",(identifier,account["user_id"]))
                return self.respond(201,{"id":identifier,"name":name,"role":"owner"})
            if path=="/api/members":
                role=payload.get("role")
                if role not in {"planner","supervisor","remove"}: raise ValueError("Choose planner, supervisor, or remove access")
                with db_session() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row=db.execute("SELECT id FROM users WHERE email=?",(str(payload.get("email","")).strip().casefold(),)).fetchone()
                    if role=="remove" and not row: raise LookupError("Project member not found")
                    user={"id":row["id"]} if row else auth.create_user(db,payload)
                    existing=db.execute("SELECT role FROM memberships WHERE project_id=? AND user_id=?",(auth.project_context.get(),user["id"])).fetchone()
                    if existing and existing["role"]=="owner": raise ValueError("An owner's access cannot be changed here")
                    if role=="remove": db.execute("DELETE FROM memberships WHERE project_id=? AND user_id=?",(auth.project_context.get(),user["id"]))
                    else: db.execute("INSERT OR REPLACE INTO memberships VALUES (?,?,?)",(auth.project_context.get(),user["id"],role))
                return self.respond(201,{"user_id":user["id"],"role":role})
            match=re.fullmatch(r"/api/submissions/([A-Za-z0-9_-]{1,100})/retry",path)
            if match:
                with db_session() as db: saved=db.execute("SELECT * FROM submissions WHERE id=? AND project_id=?",(match.group(1),auth.project_context.get())).fetchone()
                if not saved: raise LookupError("Saved submission not found")
                original=json.loads(saved["payload"])
                if payload.get("analysis_mode") and payload["analysis_mode"]!=original.get("analysis_mode","rules"):
                    original.update(analysis_mode=payload["analysis_mode"],client_request_id=uid("retry"))
                result=submit_report(original)
                with db_session() as db: db.execute("UPDATE submissions SET status='complete',report_id=? WHERE id=?",(result["report_id"],saved["id"]))
                return self.respond(200,result)
            match=re.fullmatch(r"/api/captures/(cap_[a-f0-9]+)/(retry|manual)",path)
            if match:
                with db_session() as db: saved=db.execute("SELECT * FROM capture_assets WHERE id=?",(match.group(1),)).fetchone()
                options=json.loads(saved["metadata"]).get("capture_options",{})
                if match.group(2)=="manual":
                    text=payload.get("text","")
                    if not isinstance(text,str) or not text.strip() or len(text)>12000: raise ValueError("Enter the source text, up to 12,000 characters")
                    row={"text":text.strip(),"source_row":None,"method":"manual","confidence":None,"warnings":["Manually transcribed source; check against the original"]}
                    metadata={"pages":[row]} if saved["kind"]=="document" else {"text":text.strip(),"warnings":row["warnings"]}
                    metadata.update(verification="confirmed_by_submitter",processing_status="manual",capture_options=options)
                    with db_session() as db: db.execute("UPDATE capture_assets SET metadata=? WHERE id=?",(json.dumps(metadata),saved["id"]))
                    return self.respond(200,{"capture_asset_id":saved["id"],"filename":saved["filename"],"original_url":f"/api/captures/{saved['id']}/original",**metadata})
                raw=(CAPTURE_DIR/saved["id"]).read_bytes()
                content=raw.decode() if Path(saved["filename"]).suffix.lower() in {".txt",".eml"} else base64.b64encode(raw).decode()
                return self.respond(200,process_capture(saved["kind"],{"filename":saved["filename"],"content":content,**options},saved["id"]))
            if path == "/api/preview":
                return self.respond(200, preview_report(payload))
            if path == "/api/schedules/import":
                return self.respond(201, import_schedule(payload.get("filename", ""), payload.get("content", "")))
            if path == "/api/reports":
                return self.respond(201, submit_report(payload))
            if path == "/api/documents/extract":
                return self.respond(201, process_capture("document",payload))
            if path == "/api/voice/transcribe":
                return self.respond(201, process_capture("voice",payload))
            if path == "/api/analytics/scenario":
                return self.respond(200, analytics_payload(payload))
            match = re.fullmatch(r"/api/events/(evt_[a-f0-9]+)/clarify", path)
            if match:
                return self.respond(200, clarify_event(match.group(1), payload.get("answer", "")))
            match = re.fullmatch(r"/api/events/(evt_[a-f0-9]+)/decision", path)
            if match:
                return self.respond(200, decide_event(match.group(1), payload))
            if path == "/api/exports":
                result = build_export()
                return self.respond(201 if result["id"] else 200, result)
            match = re.fullmatch(r"/api/events/(evt_[a-f0-9]+)/checks", path)
            if match:
                return self.respond(200, check_proposal(match.group(1), payload))
            if path == "/api/demo/load":
                fixture = ROOT / "data" / "samples" / "pump-station.xer"
                return self.respond(201, import_schedule(fixture.name, fixture.read_text()))
            return self.respond(404, {"error": "Not found"})
        except auth.AccessError as exc:
            self.respond(exc.status,{"error":str(exc),"code":"access_denied"})
        except LookupError as exc:
            self.respond(404, {"error": str(exc)})
        except (AiUnavailable, AiResponseError) as exc:
            self.respond(503, {"error": str(exc),"retryable":True,"saved_submission_id":getattr(exc,"submission_id",None),"capture_asset_id":getattr(exc,"capture_asset_id",None),"fallback_available":True})
        except ScheduleConflict as exc:
            self.respond(409, {"error": str(exc), "code": "schedule_conflict"})
        except (ValueError, ScheduleError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc),"saved_submission_id":getattr(exc,"submission_id",None),"capture_asset_id":getattr(exc,"capture_asset_id",None),"fallback_available":bool(getattr(exc,"capture_asset_id",None))})
        except Exception as exc:
            self.respond(500, {"error": "Processing failed. The saved source can be retried.","saved_submission_id":getattr(exc,"submission_id",None),"capture_asset_id":getattr(exc,"capture_asset_id",None),"retryable":True})
        finally: self.clear_context()


def main() -> None:
    load_local_env()
    init_db()
    host = os.environ.get("CARRICK_HOST", "127.0.0.1")
    if host not in {"127.0.0.1","localhost","::1"} and not os.environ.get("CARRICK_PUBLIC_ORIGIN","").startswith("https://"):
        raise ValueError("Shared hosting requires CARRICK_PUBLIC_ORIGIN with HTTPS and a TLS reverse proxy")
    port = int(os.environ.get("CARRICK_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Carrick running at http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
