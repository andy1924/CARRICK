"""Database-backed accounts, scoped memberships and opaque cookie sessions."""
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import time
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlparse

project_context = contextvars.ContextVar("carrick_project", default=None)
user_context = contextvars.ContextVar("carrick_user", default=None)
password_slots=threading.BoundedSemaphore(2)


class AccessError(Exception):
    def __init__(self,message,status=403): self.status=status; super().__init__(message)


def init_auth(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memberships(project_id TEXT REFERENCES projects(id),user_id TEXT REFERENCES users(id),role TEXT NOT NULL CHECK(role IN ('owner','planner','supervisor')),PRIMARY KEY(project_id,user_id));
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL,last_seen REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS login_attempts(identity TEXT PRIMARY KEY,count INTEGER NOT NULL,started REAL NOT NULL);
    INSERT OR IGNORE INTO projects VALUES ('prj_default','Project workspace');
    """)
    for table in ("schedule_versions","capture_assets","processing_runs"):
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if "project_id" not in columns: db.execute(f"ALTER TABLE {table} ADD COLUMN project_id TEXT NOT NULL DEFAULT 'prj_default'")
        db.execute(f"CREATE INDEX IF NOT EXISTS {table}_project_idx ON {table}(project_id)")


def password_hash(password,salt=None):
    if not isinstance(password,str) or not 12 <= len(password) <= 256: raise ValueError("Use a password between 12 and 256 characters")
    salt = salt or secrets.token_hex(16)
    if not password_slots.acquire(timeout=2): raise AccessError("Sign-in is busy. Retry shortly.",429)
    try: digest = hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=131072,r=8,p=1,maxmem=256*1024*1024).hex()
    finally: password_slots.release()
    return salt+":"+digest


def create_user(db,payload):
    email = str(payload.get("email","")).strip().casefold()
    name = str(payload.get("name","")).strip()[:100]
    if not name or "@" not in email or len(email)>254: raise ValueError("Enter a name and valid email address")
    identifier = "usr_"+secrets.token_hex(12)
    digest = password_hash(payload.get("password"))
    db.execute("INSERT INTO users VALUES (?,?,?,?)",(identifier,email,name,digest))
    return {"id":identifier,"email":email,"name":name}


def new_session(db,user):
    token,csrf = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    stamp=time.time()
    db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user["id"],csrf,stamp+12*3600,stamp))
    return token,{**user,"csrf":csrf}


def setup(db,payload):
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT 1 FROM users LIMIT 1").fetchone(): raise AccessError("Workspace setup is already complete")
    user=create_user(db,payload)
    db.execute("INSERT INTO memberships VALUES ('prj_default',?,'owner')",(user["id"],))
    return new_session(db,user)


def login(db,payload,remote):
    email=str(payload.get("email","")).strip().casefold()
    identity=hashlib.sha256((remote+"|"+email).encode()).hexdigest()
    stamp=time.time()
    attempt=db.execute("SELECT * FROM login_attempts WHERE identity=?",(identity,)).fetchone()
    if attempt and attempt["started"]>stamp-900 and attempt["count"]>=10: raise AccessError("Too many attempts. Try again in 15 minutes.",429)
    row=db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
    password=payload.get("password","")
    valid=False
    if isinstance(password,str) and 12<=len(password)<=256:
        salt=row["password_hash"].split(":")[0] if row else "0"*32
        computed=password_hash(password,salt)
        valid=bool(row and hmac.compare_digest(computed,row["password_hash"]))
    if not valid:
        count=attempt["count"]+1 if attempt and attempt["started"]>stamp-900 else 1
        db.execute("INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)",(identity,count,attempt["started"] if count>1 else stamp))
        return None,None
    db.execute("DELETE FROM login_attempts WHERE identity=?",(identity,))
    return new_session(db,{key:row[key] for key in ("id","email","name")})


def session(db,headers):
    cookie=SimpleCookie()
    try: cookie.load(headers.get("Cookie",""))
    except Exception: raise AccessError("Sign in to continue",401)
    token=cookie.get("carrick_session")
    hashed=hashlib.sha256(token.value.encode()).hexdigest() if token else ""
    row=db.execute("SELECT s.*,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",(hashed,)).fetchone()
    if not row or row["expires"]<time.time() or row["last_seen"]<time.time()-1800: raise AccessError("Sign in to continue",401)
    db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",(time.time(),hashed))
    return dict(row)


def memberships(db,user_id):
    return [dict(row) for row in db.execute("SELECT p.id,p.name,m.role FROM projects p JOIN memberships m ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.name,p.id",(user_id,))]


def require_project(db,headers,session,planner=False,owner=False):
    project=headers.get("X-Carrick-Project","")
    row=db.execute("SELECT role FROM memberships WHERE project_id=? AND user_id=?",(project,session["user_id"])).fetchone()
    if not row: raise AccessError("You do not have access to this project")
    if owner and row["role"]!="owner" or planner and row["role"] not in {"owner","planner"}: raise AccessError("This action requires a project planner")
    return project,row["role"]


def same_origin(headers):
    configured=os.environ.get("CARRICK_PUBLIC_ORIGIN")
    expected=configured or "http://"+headers.get("Host","")
    if headers.get("Origin") and headers["Origin"]!=expected: raise AccessError("Request origin is not allowed")
    if headers.get("Sec-Fetch-Site") == "cross-site": raise AccessError("Cross-site requests are not allowed")
    if not headers.get("Content-Type","").startswith("application/json"): raise AccessError("JSON request required")


def valid_host(headers):
    host=urlparse("http://"+headers.get("Host","")).hostname
    expected=urlparse(os.environ.get("CARRICK_PUBLIC_ORIGIN","")).hostname
    if host not in ({expected} if expected else {"localhost","127.0.0.1","::1"}):
        raise AccessError("Host is not allowed")


def require_csrf(headers,session):
    same_origin(headers)
    if not hmac.compare_digest(headers.get("X-CSRF-Token",""),session["csrf"]): raise AccessError("Session changed; sign in again before submitting")


def cookie(token):
    secure="; Secure" if os.environ.get("CARRICK_PUBLIC_ORIGIN","").startswith("https://") else ""
    return f"carrick_session={token}; HttpOnly; SameSite=Strict; Path=/api; Max-Age={43200 if token else 0}"+secure
