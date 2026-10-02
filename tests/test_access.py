"""Actual HTTP authorization gates with an isolated database and server."""
import http.client
import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
from unittest import TestCase
import services.api.app as app

class AccessTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory();cls.old_db,cls.old_capture=app.DB_PATH,app.CAPTURE_DIR
        app.DB_PATH=Path(cls.temp.name)/"auth.sqlite3";app.CAPTURE_DIR=Path(cls.temp.name)/"captures";app.init_db()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.port=cls.server.server_port
        cls.cookie="";cls.csrf="";cls.project="prj_default"
        cls.call("/api/auth/setup",{"email":"owner@example.test","name":"Owner","password":"Unit-fixture-password-2026"})
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();app.DB_PATH,app.CAPTURE_DIR=cls.old_db,cls.old_capture;cls.temp.cleanup()
    @classmethod
    def call(cls,path,payload=None,headers=None):
        connection=http.client.HTTPConnection("127.0.0.1",cls.port)
        request_headers={"Content-Type":"application/json","Cookie":cls.cookie,"X-CSRF-Token":cls.csrf,"X-Carrick-Project":cls.project,**(headers or {})}
        connection.request("POST" if payload is not None else "GET",path,json.dumps(payload) if payload is not None else None,request_headers)
        response=connection.getresponse();data=json.loads(response.read());cookie=response.getheader("Set-Cookie")
        if cookie: cls.cookie=cookie.split(";",1)[0]
        if "csrf" in data: cls.csrf=data["csrf"]
        status=response.status;connection.close();return status,data
    def test_login_required_and_csrf_enforced(self):
        self.assertEqual(self.call("/api/events",headers={"Cookie":""})[0],401)
        self.assertEqual(self.call("/api/projects",{"name":"CSRF blocked"},{"X-CSRF-Token":"wrong"})[0],403)
        self.assertEqual(self.call("/api/projects",{"name":"Origin blocked"},{"Origin":"https://attacker.example"})[0],403)
    def test_supervisor_write_and_project_isolation_gates(self):
        status,_=self.call("/api/members",{"email":"supervisor@example.test","name":"Supervisor","password":"Unit-fixture-password-2026","role":"supervisor"});self.assertEqual(status,201)
        _,other=self.call("/api/projects",{"name":"Separate project"})
        owner_cookie,owner_csrf=self.cookie,self.csrf
        self.call("/api/auth/login",{"email":"supervisor@example.test","password":"Unit-fixture-password-2026"})
        self.assertEqual(self.call("/api/exports",{})[0],403)
        self.assertEqual(self.call("/api/schedules/import",{"filename":"x.csv","content":"activity_id,activity_name\nA,Test"})[0],403)
        self.assertEqual(self.call("/api/events",headers={"X-Carrick-Project":other["id"]})[0],403)
        self.assertEqual(self.call("/api/members",{"email":"x@example.test","name":"x","password":"Unit-fixture-password-2026","role":"planner"})[0],403)
        type(self).cookie,type(self).csrf=owner_cookie,owner_csrf
    def test_session_logout_invalidates_cookie(self):
        prior=self.cookie
        self.call("/api/auth/logout",{})
        self.assertEqual(self.call("/api/events",headers={"Cookie":prior})[0],401)
        self.call("/api/auth/login",{"email":"owner@example.test","password":"Unit-fixture-password-2026"})

    def test_resource_ids_cannot_cross_project_boundaries(self):
        from services.api import auth
        from base64 import b64encode
        from unittest.mock import patch
        with patch.object(app,"extract_document",return_value=[]):
            status,capture=self.call("/api/documents/extract",{"filename":"source.png","content":b64encode(b"fixture").decode()})
        self.assertEqual(status,201)
        status,other=self.call("/api/projects",{"name":"Resource isolation"})
        self.assertEqual(status,201)
        self.assertEqual(self.call(capture["original_url"],headers={"X-Carrick-Project":other["id"]})[0],404)
        self.assertEqual(self.call(f"/api/captures/{capture['capture_asset_id']}/manual",{"text":"text"},{"X-Carrick-Project":other["id"]})[0],404)
        with app.db_session() as db:
            self.assertEqual(db.execute("SELECT project_id FROM capture_assets WHERE id=?",(capture["capture_asset_id"],)).fetchone()[0],"prj_default")
        # HTTP handler context never survives a request into unrelated work.
        self.assertIsNone(auth.project_context.get())

    def test_access_revocation_invalidates_an_existing_session(self):
        self.call("/api/members",{"email":"revoked@example.test","name":"Revoked","password":"Unit-fixture-password-2026","role":"planner"})
        owner_cookie,owner_csrf=self.cookie,self.csrf
        self.call("/api/auth/login",{"email":"revoked@example.test","password":"Unit-fixture-password-2026"})
        member_cookie,member_csrf=self.cookie,self.csrf
        self.assertEqual(self.call("/api/events")[0],200)
        type(self).cookie,type(self).csrf=owner_cookie,owner_csrf
        self.assertEqual(self.call("/api/members",{"email":"revoked@example.test","role":"remove"})[0],201)
        self.assertEqual(self.call("/api/events",headers={"Cookie":member_cookie,"X-CSRF-Token":member_csrf})[0],403)
