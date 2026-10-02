from base64 import b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date
from unittest import TestCase
from unittest.mock import patch
import services.api.app as app
from services.api import auth
from services.worker.ai import AiUnavailable
from services.worker.engine import parse_schedule
from services.worker.validation import actual_checks

FIXTURE=Path(__file__).resolve().parents[1]/"data/samples/pump-station.xer"

class ReliabilityTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.old_db,self.old_capture=app.DB_PATH,app.CAPTURE_DIR
        app.DB_PATH=Path(self.temp.name)/"test.sqlite3";app.CAPTURE_DIR=Path(self.temp.name)/"captures";app.init_db()
        self.network=patch("urllib.request.urlopen",side_effect=AssertionError("No network providers in tests"));self.network.start()
        self.version=app.import_schedule(FIXTURE.name,FIXTURE.read_text())
    def tearDown(self):
        self.network.stop();app.DB_PATH,app.CAPTURE_DIR=self.old_db,self.old_capture;self.temp.cleanup()
    def report(self,text): return app.submit_report({"content":text,"event_date":"2026-10-01"})["events"][0]
    def test_provider_failure_is_persisted_before_inference_and_can_fallback(self):
        payload={"content":"North pipeline welding started today","event_date":"2026-10-01","analysis_mode":"ai","client_request_id":"durable-request"}
        with patch.object(app,"ai_status",return_value={"available":False,"message":"Mock unavailable"}):
            with self.assertRaises(AiUnavailable): app.submit_report(payload)
        with app.db_session() as db:
            row=db.execute("SELECT * FROM submissions WHERE id='durable-request'").fetchone();self.assertEqual(row["status"],"failed");self.assertIn(payload["content"],row["payload"])
        result=app.submit_report({**payload,"analysis_mode":"rules","client_request_id":"fallback-request","fallback_for":"durable-request"})
        self.assertEqual(len(result["events"]),1)
        with app.db_session() as db: self.assertEqual(db.execute("SELECT status FROM submissions WHERE id='durable-request'").fetchone()[0],"complete")
    def test_failed_capture_retains_original(self):
        with patch.object(app,"extract_document",side_effect=ValueError("Mock unavailable")):
            with self.assertRaises(ValueError) as caught: app.process_capture("document",{"filename":"scan.png","content":b64encode(b"synthetic scan bytes").decode()})
        identifier=caught.exception.capture_asset_id
        self.assertEqual((app.CAPTURE_DIR/identifier).read_bytes(),b"synthetic scan bytes")
        with app.db_session() as db: self.assertIn("needs_retry",db.execute("SELECT metadata FROM capture_assets WHERE id=?",(identifier,)).fetchone()[0])
    def test_export_roundtrip_preserves_unrelated_records_and_approval_boundary(self):
        source=FIXTURE.read_text().replace('%T\tTASK\n','%T\tCALENDAR\n%F\tclndr_id\tclndr_name\n%R\t99\tKeep this calendar\n%T\tTASK\n')
        version=app.import_schedule("synthetic.xer",source)
        approved=self.report("Main foundation concrete pour finished today");self.report("South pipeline welding started today")
        app.decide_event(approved["id"],{"action":"approve","activity_id":"CV-102","event_date":"2026-10-01"})
        export=app.build_export()
        with app.db_session() as db: row=db.execute("SELECT * FROM exports WHERE id=?",(export["id"],)).fetchone();original=db.execute("SELECT content FROM schedule_versions WHERE id=?",(version["id"],)).fetchone()[0]
        self.assertEqual(original,source);self.assertIn("Keep this calendar",row["xer_content"])
        activities,relations,_=parse_schedule(row["xer_content"],"updated.xer");by_id={a["external_id"]:a for a in activities}
        self.assertEqual(by_id["CV-102"]["actual_finish"][:10],"2026-10-01");self.assertEqual(by_id["PI-302"]["actual_start"],"")
        self.assertEqual(relations,parse_schedule(source,"original.xer")[1]);self.assertTrue(export["manifest"]["round_trip_verified"])
    def test_repeated_actual_is_consolidated_not_reexported(self):
        event=self.report("North pipeline welding started today");app.decide_event(event["id"],{"action":"approve","activity_id":"PI-301"});app.build_export()
        event=self.report("We began the north pipeline weld today")
        decision=app.decide_event(event["id"],{"action":"approve","activity_id":"PI-301"});self.assertEqual(decision["status"],"duplicate")
        with self.assertRaisesRegex(ValueError,"no approved events"): app.build_export()
    def test_conflicting_actual_cannot_be_overridden_by_reason(self):
        event=self.report("North pipeline welding started today");app.decide_event(event["id"],{"action":"approve","activity_id":"PI-301"})
        event=self.report("North pipeline weld commenced yesterday")
        with self.assertRaisesRegex(ValueError,"already has actual start"):
            app.decide_event(event["id"],{"action":"approve","activity_id":"PI-301","event_date":"2026-09-30","reason":"Cannot override actual"})

class DependencyTests(TestCase):
    def test_all_relationship_types_use_their_correct_actual_endpoints(self):
        a={"external_id":"A","actual_start":"2026-09-28","actual_finish":"2026-09-30"};b={"external_id":"B","actual_start":"","actual_finish":""}
        for kind,event_kind,proposed in [("FS","actual_start","2026-09-29"),("SS","actual_start","2026-09-27"),("FF","actual_finish","2026-09-29"),("SF","actual_finish","2026-09-27")]:
            with self.subTest(kind=kind):
                checks=actual_checks({"kind":event_kind,"event_date":proposed},"B",[a,b],[{"predecessor":"A","successor":"B","kind":kind,"lag":0}],date(2026,10,2))
                self.assertIn("sequence_conflict",[c["code"] for c in checks])
    def test_outgoing_relationship_conflict_and_missing_predecessor(self):
        tasks=[{"external_id":"A","actual_start":"2026-09-28","actual_finish":""},{"external_id":"B","actual_start":"2026-10-01","actual_finish":""}]
        edges=[{"predecessor":"A","successor":"B","kind":"PR_FS","lag":"0"}]
        checks=actual_checks({"kind":"actual_finish","event_date":"2026-10-02"},"A",tasks,edges,date(2026,10,2));self.assertIn("sequence_conflict",[c["code"] for c in checks])
        checks=actual_checks({"kind":"actual_start","event_date":"2026-10-01"},"B",tasks,edges,date(2026,10,2));self.assertTrue(any(c["message"].startswith("Predecessor A") for c in checks))
    def test_unknown_dependency_endpoint_and_cycles_are_not_silent(self):
        tasks=[{"external_id":"A"},{"external_id":"B"}];edges=[{"predecessor":"A","successor":"B","kind":"SS","lag":"0"},{"predecessor":"B","successor":"A","kind":"SS","lag":"0"},{"predecessor":"C","successor":"A","kind":"FS","lag":"0"}]
        checks=actual_checks({"kind":"actual_start","event_date":"2026-10-01"},"A",tasks,edges,date(2026,10,2));self.assertTrue({"dependency_cycle","missing_dependency_endpoint"}.issubset({c["code"] for c in checks}))
