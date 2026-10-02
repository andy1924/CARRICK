"""Isolated loopback server for browser tests. Never uses the live workspace DB."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import services.api.app as app
from tests.fakes import FakeAIClient, document, speech

def main():
    with TemporaryDirectory(prefix="carrick-e2e-") as temp:
        app.DB_PATH=Path(temp)/"test.sqlite3";app.CAPTURE_DIR=Path(temp)/"captures";app.init_db()
        status={"available":True,"mode":"openai","reranker":"llm","model":"fake-structured-model","message":"Isolated mock provider"}
        capture={"ocr":{"available":True},"voice":{"available":True},"vision":{"available":False}}
        with patch.object(app,"model_client",FakeAIClient),patch.object(app,"ai_status",return_value=status),patch.object(app,"extract_document",document),patch.object(app,"transcribe_audio",speech),patch.object(app,"capture_status",return_value=capture),patch("urllib.request.urlopen",side_effect=AssertionError("Test server must not call external providers")):
            server=ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("CARRICK_TEST_PORT","8766"))),app.Handler)
            print("Isolated browser test server ready",flush=True)
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()

if __name__=="__main__": main()
