"""Meaningful checks for the local report-to-export path."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import services.api.app as app
from services.worker.engine import extract_events, parse_schedule, rank_activities, route_event


FIXTURE = Path(__file__).resolve().parents[1] / "data" / "samples" / "pump-station.xer"


class EngineTests(unittest.TestCase):
    def test_schedule_and_ambiguous_matching(self):
        activities, relationships, kind = parse_schedule(FIXTURE.read_text(), FIXTURE.name)
        self.assertEqual((kind, len(activities), len(relationships)), ("xer", 12, 7))
        event = extract_events("Started welding today", "2026-10-01", "piping")[0]
        candidates = rank_activities(event, activities)
        self.assertEqual({candidates[0]["activity_id"], candidates[1]["activity_id"]}, {"PI-301", "PI-302"})
        status, warnings = route_event(event, candidates)
        self.assertEqual(status, "needs_review")
        self.assertIn("Several activities are plausible", warnings)

    def test_tense_and_negation_do_not_create_actuals(self):
        events = extract_events("Testing not completed; will finish tomorrow", "2026-10-01")
        self.assertEqual([event["kind"] for event in events], ["in_progress", "forecast_finish"])
        self.assertTrue(all(route_event(event, [])[0] == "needs_review" for event in events))

    def test_public_preview_uses_sample_without_writing_data(self):
        result = app.preview_report({"content": "Started welding today"})
        self.assertFalse(result["saved"])
        self.assertEqual(result["events"][0]["status"], "needs_review")
        self.assertEqual({candidate["activity_id"] for candidate in result["events"][0]["candidates"][:2]},
                         {"PI-301", "PI-302"})
        with self.assertRaisesRegex(ValueError, "1,000"):
            app.preview_report({"content": "a" * 1001})


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.old_path = app.DB_PATH
        app.DB_PATH = Path(self.temp.name) / "app.sqlite3"
        app.init_db()
        self.schedule = app.import_schedule(FIXTURE.name, FIXTURE.read_text())

    def tearDown(self):
        app.DB_PATH = self.old_path
        self.temp.cleanup()

    def test_text_review_and_approved_export(self):
        report = app.submit_report({
            "source_kind": "text",
            "content": "Finished pouring the main foundation today; Started welding today",
            "event_date": "2026-10-01",
            "discipline": "civil",
        })
        self.assertEqual(len(report["events"]), 2)
        first, second = report["events"]
        self.assertEqual(first["candidates"][0]["activity_id"], "CV-102")
        self.assertEqual(second["status"], "needs_review")
        app.decide_event(first["id"], {"action": "approve", "activity_id": "CV-102", "event_date": "2026-10-01"})
        output = app.build_export()
        self.assertEqual(output["manifest"]["row_count"], 1)
        with app.connection() as db:
            exported = db.execute("SELECT content FROM exports WHERE id=?", (output["id"],)).fetchone()[0]
            source = db.execute("SELECT content FROM schedule_versions WHERE id=?", (self.schedule["id"],)).fetchone()[0]
        self.assertIn("CV-102,actual_finish,2026-10-01", exported)
        self.assertEqual(source, FIXTURE.read_text())
        self.assertEqual(app.summary()["counts"], {"exported": 1, "needs_review": 1})

    def test_spreadsheet_keeps_row_provenance(self):
        report = app.submit_report({
            "source_kind": "spreadsheet",
            "filename": "updates.csv",
            "content": "report_text,event_date,discipline,location\nNorth pipeline welding started,2026-10-01,piping,north\n",
        })
        self.assertEqual(len(report["events"]), 1)
        with app.connection() as db:
            row = db.execute("SELECT source_row FROM events WHERE id=?", (report["events"][0]["id"],)).fetchone()
        self.assertEqual(row["source_row"], 2)

    def test_finish_never_fills_missing_start(self):
        report = app.submit_report({"source_kind": "text", "content": "Pump B installed today", "event_date": "2026-10-01"})
        event = report["events"][0]
        self.assertEqual(event["kind"], "actual_finish")
        self.assertIn("Actual start is not recorded", event["warnings"])
        with app.connection() as db:
            activity = db.execute("SELECT actual_start FROM activities WHERE external_id='ME-202'").fetchone()
        self.assertFalse(activity["actual_start"])

    def test_forecast_can_be_kept_without_exporting_an_actual(self):
        report = app.submit_report({"source_kind": "text", "content": "Pump A will finish tomorrow", "event_date": "2026-10-01"})
        event = report["events"][0]
        self.assertEqual(event["kind"], "forecast_finish")
        self.assertEqual(event["event_date"], "2026-10-02")
        result = app.decide_event(event["id"], {"action": "record", "activity_id": "ME-201", "reason": "Forecast only"})
        self.assertEqual(result["status"], "recorded")
        with self.assertRaisesRegex(ValueError, "no approved events"):
            app.build_export()


if __name__ == "__main__":
    unittest.main()
