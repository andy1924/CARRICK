"""Meaningful checks for the local report-to-export path."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import importlib.util

import services.api.app as app
from services.worker.ai import _validated_event
from services.worker.ingest import document_rows
from services.worker.engine import extract_events, parse_schedule, rank_activities, route_event


FIXTURE = Path(__file__).resolve().parents[1] / "data" / "samples" / "pump-station.xer"


class EngineTests(unittest.TestCase):
    def test_schedule_and_ambiguous_matching(self):
        activities, relationships, kind = parse_schedule(FIXTURE.read_text(), FIXTURE.name)
        self.assertEqual((kind, len(activities), len(relationships)), ("xer", 12, 7))
        self.assertIn({"predecessor": "CV-101", "successor": "CV-102", "kind": "PR_FS", "lag": "0"}, relationships)
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

    def test_email_body_can_be_ingested_without_copying_it(self):
        rows = document_rows("update.eml", "From: supervisor@example.test\nSubject: Update\n\nNorth pipeline welding started today")
        self.assertEqual(rows, [{"text": "North pipeline welding started today", "source_row": None}])

    def test_model_claim_must_quote_the_source(self):
        self.assertIsNone(_validated_event({"quote": "Pump A installed", "kind": "actual_finish",
                                            "event_date": "2026-10-01"}, "Pump B installed", "2026-10-01", "", ""))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "PDF dependency is optional")
    def test_pdf_text_layer_keeps_page_number(self):
        from base64 import b64encode
        from io import BytesIO
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (North pipeline welding started today) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        output = BytesIO()
        writer.write(output)
        rows = document_rows("update.pdf", b64encode(output.getvalue()).decode())
        self.assertEqual(rows, [{"text": "North pipeline welding started today", "source_row": 1}])


class FakeAIClient:
    embedding_model = "fake-embedding"
    model = "fake-structured-model"

    def embed(self, texts):
        return [[float("north" in text.lower()), float("pump" in text.lower()), 1.0] for text in texts]

    def structured(self, name, instructions, data, schema):
        if name == "field_events":
            return {"events": [{"quote": data["report"], "kind": "actual_start", "event_date": "2026-10-01",
                                "discipline": "piping", "location": ""}]}
        if "Clarification from site: north" in data["field_event"]:
            return {"ranked_ids": ["NEW-999", "PI-301", "PI-302"], "ambiguous": False,
                    "reason": "North matches the pipeline location", "clarification_question": ""}
        return {"ranked_ids": ["NEW-999", "PI-301", "PI-302"], "ambiguous": True,
                "reason": "Both pipeline welds fit the note", "clarification_question": "North or south pipeline?"}

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

    def test_ai_retrieval_review_and_clarification_keep_source_auditable(self):
        with patch.object(app, "OpenAIClient", FakeAIClient), patch.object(app, "ai_status", return_value={"available": True, "reranker": "llm"}):
            report = app.submit_report({"source_kind": "text", "analysis_mode": "ai",
                                        "content": "Started welding today", "event_date": "2026-10-01"})
            event = report["events"][0]
            self.assertEqual(report["analysis_mode"], "ai")
            self.assertEqual(event["status"], "needs_review")
            self.assertEqual(event["candidates"][0]["activity_id"], "PI-301")
            self.assertEqual(event["clarification_question"], "North or south pipeline?")
            refined = app.clarify_event(event["id"], "north")
        self.assertEqual(refined["candidates"][0]["activity_id"], "PI-301")
        self.assertFalse(refined["clarification_question"])
        with app.connection() as db:
            saved = db.execute("SELECT analysis_mode, model_name, clarification_answer FROM events WHERE id=?", (event["id"],)).fetchone()
            audit = db.execute("SELECT action FROM audit WHERE event_id=?", (event["id"],)).fetchone()
            indexed = db.execute("SELECT count(*) FROM activity_embeddings").fetchone()[0]
        self.assertEqual(tuple(saved), ("ai", "fake-structured-model", "north"))
        self.assertEqual(audit[0], "clarify")
        self.assertEqual(indexed, 12)

    def test_predecessor_warning_is_attached_to_start_proposal(self):
        report = app.submit_report({"source_kind": "text", "content": "Pump A started today",
                                    "event_date": "2026-10-01"})
        self.assertTrue(any("Predecessor CV-103" in warning for warning in report["events"][0]["warnings"]))


if __name__ == "__main__":
    unittest.main()
