"""Local Carrick API and static web server. Run with `python3 -m services.api.app`."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from services.worker.engine import ScheduleError, extract_events, parse_schedule, rank_activities, route_event
from services.worker.ai import AiResponseError, AiUnavailable, OpenAIClient, ai_status, analyze_report, activity_card, rank_event
from services.worker.ingest import document_rows


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
DB_PATH = Path(os.environ.get("CARRICK_DB", ROOT / "data" / "private" / "carrick.sqlite3"))
MAX_BODY = 3_000_000


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
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
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        for name, definition in (("analysis_mode", "TEXT NOT NULL DEFAULT 'rules'"),
                                 ("model_name", "TEXT"), ("clarification_question", "TEXT"),
                                 ("clarification_answer", "TEXT")):
            if name not in columns:
                db.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")


def latest_version(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM schedule_versions ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()


def activities_for(db: sqlite3.Connection, version_id: str) -> list[dict]:
    return [dict(row) for row in db.execute(
        "SELECT * FROM activities WHERE version_id=? ORDER BY external_id", (version_id,)
    )]


def relationships_for(db: sqlite3.Connection, version_id: str) -> list[dict]:
    source_ids = {row["source_key"]: row["external_id"] for row in db.execute(
        "SELECT source_key, external_id FROM activities WHERE version_id=?", (version_id,))}
    rows = [dict(row) for row in db.execute(
        "SELECT predecessor, successor, kind, lag FROM relationships WHERE version_id=?", (version_id,)
    )]
    for row in rows:
        row["predecessor"] = source_ids.get(row["predecessor"], row["predecessor"])
        row["successor"] = source_ids.get(row["successor"], row["successor"])
    return rows


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
    return value


def import_schedule(filename: str, content: str) -> dict:
    if not filename or not content:
        raise ValueError("Choose a non-empty schedule file")
    activities, relationships, file_format = parse_schedule(content, filename)
    version_id = uid("sch")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with db_session() as db:
        db.execute("INSERT INTO schedule_versions VALUES (?,?,?,?,?,?)",
                   (version_id, filename, file_format, checksum, content, now()))
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


def submit_report(payload: dict) -> dict:
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
        version = latest_version(db)
        if not version:
            raise ValueError("Import a schedule before submitting reports")
        activities = activities_for(db, version["id"])
        relationships = relationships_for(db, version["id"])
        version_id = version["id"]
    client = None
    vectors = None
    if analysis_mode == "ai":
        status = ai_status()
        if not status["available"]:
            raise AiUnavailable(status["message"])
        client = OpenAIClient()
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
            warnings.extend(dependency_warnings(event, candidates[0]["activity_id"] if candidates else "",
                                                activities, relationships))
            if event["kind"] == "actual_finish" and candidates:
                activity = next((a for a in activities if a["external_id"] == candidates[0]["activity_id"]), None)
                if activity and not activity["actual_start"]:
                    warnings.append("Actual start is not recorded")
            output.append(dict(event, source_row=row["source_row"],
                               status="needs_review" if warnings else event["status"], warnings=warnings))
    source_content = (payload.get("content", "") if payload.get("source_kind") != "document"
                      else "\n\n".join(row["text"] for row in rows))
    with db_session() as db:
        report_id = uid("rpt")
        db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                   (report_id, version_id, payload.get("source_kind", "text"),
                    payload.get("filename", ""), source_content, now()))
        for event in output:
            event_id = uid("evt")
            db.execute("""INSERT INTO events
              (id,report_id,source_row,text,kind,event_date,discipline,location,status,candidates,warnings,
               analysis_mode,model_name,clarification_question)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (event_id, report_id, event["source_row"], event["text"], event["kind"],
               event["event_date"], event["discipline"], event["location"], event["status"],
               json.dumps(event["candidates"]), json.dumps(event["warnings"]), analysis_mode,
               client.model if client else "", event.get("clarification_question", "")))
            event["id"] = event_id
        return {"report_id": report_id, "schedule_version": version_id,
                "analysis_mode": analysis_mode, "events": output}


def clarify_event(event_id: str, answer: str) -> dict:
    answer = answer.strip()
    if not answer or len(answer) > 400:
        raise ValueError("Clarification must be between 1 and 400 characters")
    with db_session() as db:
        row = db.execute("""SELECT e.*, r.version_id FROM events e JOIN reports r ON r.id=e.report_id
                            WHERE e.id=?""", (event_id,)).fetchone()
        if not row:
            raise LookupError("Event not found")
        if row["analysis_mode"] != "ai" or row["status"] not in {"needs_review", "staged"}:
            raise ValueError("Only pending AI suggestions can be clarified")
        activities = activities_for(db, row["version_id"])
        relationships = relationships_for(db, row["version_id"])
        version_id = row["version_id"]
        event = dict(row)
    status = ai_status()
    if not status["available"]:
        raise AiUnavailable(status["message"])
    client = OpenAIClient()
    vectors = embedding_index(version_id, activities, client)
    candidates, ambiguous, question = rank_event(event, activities, relationships, vectors, client,
                                                 status["reranker"], clarification=answer)
    warnings = [warning for warning in json.loads(event["warnings"])
                if warning not in {"Several activities are plausible"} and
                not warning.startswith("Predecessor ") and not warning.startswith("Starts before predecessor ")]
    if ambiguous:
        warnings.append("Several activities are plausible")
    warnings.extend(dependency_warnings(event, candidates[0]["activity_id"] if candidates else "",
                                        activities, relationships))
    with db_session() as db:
        changed = db.execute("""UPDATE events SET candidates=?, warnings=?, clarification_question=?, clarification_answer=?, model_name=?
                      WHERE id=? AND status IN ('needs_review','staged')""",
                   (json.dumps(candidates), json.dumps(warnings), question if ambiguous else "", answer,
                    client.model, event_id))
        if changed.rowcount != 1:
            raise ValueError("This event already has a decision")
        db.execute("INSERT INTO audit (event_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                   (event_id, "clarify", "Supervisor", json.dumps({"answer": answer,
                    "candidate_ids": [candidate["activity_id"] for candidate in candidates]}), now()))
    return {"id": event_id, "candidates": candidates, "warnings": warnings,
            "clarification_question": question if ambiguous else "", "clarification_answer": answer}


def decide_event(event_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action not in {"approve", "reject", "record"}:
        raise ValueError("Action must be approve, reject, or record")
    reason = (payload.get("reason") or "").strip()
    actor = (payload.get("actor") or "Planner").strip()[:80]
    with db_session() as db:
        event = db.execute("""SELECT e.*, r.version_id FROM events e
            JOIN reports r ON r.id=e.report_id WHERE e.id=?""", (event_id,)).fetchone()
        if not event:
            raise LookupError("Event not found")
        if event["status"] in {"approved", "rejected", "recorded", "exported"}:
            raise ValueError("This event already has a decision")
        activity_id = (payload.get("activity_id") or "").strip()
        event_date = (payload.get("event_date") or event["event_date"] or "").strip()
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
            relation_flags = dependency_warnings(
                {"kind": event["kind"], "event_date": event_date}, activity_id,
                activities_for(db, event["version_id"]), relationships_for(db, event["version_id"]))
            if relation_flags and not reason:
                raise ValueError("Add a decision note to approve an out-of-sequence actual")
            activity = db.execute("SELECT * FROM activities WHERE version_id=? AND external_id=?",
                                  (event["version_id"], activity_id)).fetchone()
            if event["kind"] == "actual_finish" and activity["actual_start"]:
                try:
                    if date.fromisoformat(event_date) < date.fromisoformat(activity["actual_start"][:10]):
                        raise ValueError("Actual finish precedes the recorded actual start")
                except ValueError as exc:
                    if "precedes" in str(exc):
                        raise
            if event["kind"] == "actual_start" and activity["actual_finish"]:
                try:
                    if date.fromisoformat(event_date) > date.fromisoformat(activity["actual_finish"][:10]):
                        raise ValueError("Actual start follows the recorded actual finish")
                except ValueError as exc:
                    if "follows" in str(exc):
                        raise
            status = "approved"
        elif action == "record":
            if activity_id and not db.execute("SELECT 1 FROM activities WHERE version_id=? AND external_id=?",
                                              (event["version_id"], activity_id)).fetchone():
                raise ValueError("Choose an activity from the imported schedule")
            if event_date:
                date.fromisoformat(event_date)
            status = "recorded"
        else:
            status = "rejected"
            activity_id = ""
        db.execute("""UPDATE events SET status=?, selected_activity=?, event_date=?,
                  decision_reason=?, decided_at=? WHERE id=?""",
                  (status, activity_id, event_date, reason, now(), event_id))
        db.execute("INSERT INTO audit (event_id,action,actor,detail,created_at) VALUES (?,?,?,?,?)",
                   (event_id, action, actor, json.dumps({"activity_id": activity_id, "event_date": event_date, "reason": reason}), now()))
        return {"id": event_id, "status": status, "activity_id": activity_id, "event_date": event_date}


def build_export() -> dict:
    with db_session() as db:
        version = latest_version(db)
        if not version:
            raise ValueError("Import a schedule first")
        rows = db.execute("""SELECT e.*, r.version_id FROM events e JOIN reports r ON r.id=e.report_id
            WHERE r.version_id=? AND e.status='approved' ORDER BY e.decided_at, e.id""", (version["id"],)).fetchall()
        if not rows:
            raise ValueError("There are no approved events to export")
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["schedule_version", "activity_id", "event_kind", "actual_date", "discipline",
                         "source_report", "source_row", "event_id", "approved_at"])
        for row in rows:
            writer.writerow([version["id"], row["selected_activity"], row["kind"], row["event_date"],
                             row["discipline"], row["report_id"], row["source_row"] or "", row["id"], row["decided_at"]])
        content = stream.getvalue()
        export_id = uid("exp")
        manifest = {"schedule_version": version["id"], "source_checksum": version["checksum"],
                    "event_ids": [row["id"] for row in rows], "row_count": len(rows),
                    "output_checksum": hashlib.sha256(content.encode()).hexdigest(),
                    "format": "csv", "created_at": now()}
        db.execute("INSERT INTO exports VALUES (?,?,?,?,?)",
                   (export_id, version["id"], content, json.dumps(manifest), now()))
        db.executemany("UPDATE events SET status='exported' WHERE id=?", [(row["id"],) for row in rows])
        return {"id": export_id, "manifest": manifest, "download": f"/api/exports/{export_id}.csv"}


def summary() -> dict:
    with db_session() as db:
        version = latest_version(db)
        if not version:
            return {"schedule": None, "counts": {}, "recent": []}
        counts = {row["status"]: row["count"] for row in db.execute("""SELECT e.status, count(*) AS count
            FROM events e JOIN reports r ON r.id=e.report_id WHERE r.version_id=? GROUP BY e.status""", (version["id"],))}
        recent = [event_record(row) for row in db.execute("""SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id
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
    def log_message(self, format: str, *args: object) -> None:
        print("%s %s" % (self.address_string(), format % args))

    def respond(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("Request body must be between 1 byte and 3 MB")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                return self.respond(200, {"status": "ok"})
            if path == "/api/ai/status":
                return self.respond(200, ai_status())
            if path == "/api/summary":
                return self.respond(200, summary())
            if path == "/api/activities":
                with db_session() as db:
                    version = latest_version(db)
                    return self.respond(200, activities_for(db, version["id"]) if version else [])
            if path == "/api/events":
                with db_session() as db:
                    version = latest_version(db)
                    rows = db.execute("""SELECT e.* FROM events e JOIN reports r ON r.id=e.report_id
                        WHERE r.version_id=? ORDER BY r.created_at DESC, e.rowid DESC""", (version["id"],)).fetchall() if version else []
                    return self.respond(200, [event_record(row) for row in rows])
            match = re.fullmatch(r"/api/exports/(exp_[a-f0-9]+)\.csv", path)
            if match:
                with db_session() as db:
                    row = db.execute("SELECT content FROM exports WHERE id=?", (match.group(1),)).fetchone()
                if not row:
                    return self.respond(404, {"error": "Export not found"})
                body = row["content"].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename=carrick-progress-{match.group(1)}.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            static = {"/": ("landing.html", "text/html"),
                      "/app": ("index.html", "text/html"), "/app/": ("index.html", "text/html"),
                      "/landing.js": ("landing.js", "text/javascript"),
                      "/landing.css": ("landing.css", "text/css"),
                      "/app.js": ("app.js", "text/javascript"),
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
                self.end_headers()
                return self.wfile.write(body)
            return self.respond(404, {"error": "Not found"})
        except Exception as exc:
            self.respond(500, {"error": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/preview":
                return self.respond(200, preview_report(payload))
            if path == "/api/schedules/import":
                return self.respond(201, import_schedule(payload.get("filename", ""), payload.get("content", "")))
            if path == "/api/reports":
                return self.respond(201, submit_report(payload))
            match = re.fullmatch(r"/api/events/(evt_[a-f0-9]+)/clarify", path)
            if match:
                return self.respond(200, clarify_event(match.group(1), payload.get("answer", "")))
            match = re.fullmatch(r"/api/events/(evt_[a-f0-9]+)/decision", path)
            if match:
                return self.respond(200, decide_event(match.group(1), payload))
            if path == "/api/exports":
                return self.respond(201, build_export())
            if path == "/api/demo/load":
                fixture = ROOT / "data" / "samples" / "pump-station.xer"
                return self.respond(201, import_schedule(fixture.name, fixture.read_text()))
            return self.respond(404, {"error": "Not found"})
        except LookupError as exc:
            self.respond(404, {"error": str(exc)})
        except (AiUnavailable, AiResponseError) as exc:
            self.respond(503, {"error": str(exc)})
        except (ValueError, ScheduleError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except Exception as exc:
            self.respond(500, {"error": str(exc)})


def main() -> None:
    init_db()
    host = os.environ.get("CARRICK_HOST", "127.0.0.1")
    port = int(os.environ.get("CARRICK_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Carrick running at http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
