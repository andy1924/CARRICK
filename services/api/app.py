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
          selected_activity TEXT, decision_reason TEXT, decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
          action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exports (
          id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES schedule_versions(id),
          content TEXT NOT NULL, manifest TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)


def latest_version(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM schedule_versions ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()


def activities_for(db: sqlite3.Connection, version_id: str) -> list[dict]:
    return [dict(row) for row in db.execute(
        "SELECT * FROM activities WHERE version_id=? ORDER BY external_id", (version_id,)
    )]


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
        raise ValueError("Source kind must be text or spreadsheet")
    return [{"text": payload.get("content", "").strip(), "source_row": None,
             "event_date": payload.get("event_date", ""),
             "discipline": payload.get("discipline", ""),
             "location": payload.get("location", "")}]


def submit_report(payload: dict) -> dict:
    rows = _report_rows(payload)
    if not rows or not any(row["text"] for row in rows):
        raise ValueError("Report has no usable text")
    for row in rows:
        if row["event_date"]:
            date.fromisoformat(row["event_date"])
    with db_session() as db:
        version = latest_version(db)
        if not version:
            raise ValueError("Import a schedule before submitting reports")
        activities = activities_for(db, version["id"])
        report_id = uid("rpt")
        db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                   (report_id, version["id"], payload.get("source_kind", "text"),
                    payload.get("filename", ""), payload.get("content", ""), now()))
        output = []
        for row in rows:
            for event in extract_events(row["text"], row["event_date"], row["discipline"], row["location"]):
                candidates = rank_activities(event, activities)
                status, warnings = route_event(event, candidates)
                if event["kind"] == "actual_finish" and candidates:
                    activity = next((a for a in activities if a["external_id"] == candidates[0]["activity_id"]), None)
                    if activity and not activity["actual_start"]:
                        warnings.append("Actual start is not recorded")
                        status = "needs_review"
                event_id = uid("evt")
                db.execute("""INSERT INTO events
                  (id,report_id,source_row,text,kind,event_date,discipline,location,status,candidates,warnings)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (event_id, report_id, row["source_row"], event["text"], event["kind"],
                   event["event_date"], event["discipline"], event["location"], status,
                   json.dumps(candidates), json.dumps(warnings)))
                output.append({"id": event_id, **event, "status": status,
                               "candidates": candidates, "warnings": warnings})
        return {"report_id": report_id, "schedule_version": version["id"], "events": output}


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
            static = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/styles.css": ("styles.css", "text/css"),
                      "/brand/carrick-mark.svg": ("brand/carrick-mark.svg", "image/svg+xml"),
                      "/brand/carrick-logo.svg": ("brand/carrick-logo.svg", "image/svg+xml")}
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
            if path == "/api/schedules/import":
                return self.respond(201, import_schedule(payload.get("filename", ""), payload.get("content", "")))
            if path == "/api/reports":
                return self.respond(201, submit_report(payload))
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
