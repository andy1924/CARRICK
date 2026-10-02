"""Turn attached text, email, and text-layer PDFs into report rows."""

from __future__ import annotations

import base64
import binascii
import io
from email import policy
from email.parser import Parser
from pathlib import Path


def document_rows(filename: str, content: str) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        text = content.strip()
        return [{"text": text, "source_row": None}] if text else []
    if suffix == ".eml":
        message = Parser(policy=policy.default).parsestr(content)
        body = message.get_body(preferencelist=("plain",)) if message.is_multipart() else message
        text = (body.get_content() if body else "").strip()
        return [{"text": text, "source_row": None}] if text else []
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF import needs pypdf. Install the optional document dependency.") from exc
        try:
            raw = base64.b64decode(content, validate=True)
        except binascii.Error as exc:
            raise ValueError("PDF content is not valid base64") from exc
        if len(raw) > 2_000_000:
            raise ValueError("PDF files must be 2 MB or smaller")
        try:
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 20:
                raise ValueError("PDF reports must have 20 pages or fewer")
            rows = [{"text": (page.extract_text() or "").strip(), "source_row": number}
                    for number, page in enumerate(reader.pages, 1)]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Could not read the PDF text layer") from exc
        if any(not row["text"] for row in rows):
            from services.worker.capture import extract_document
            rows = extract_document(filename, content)
        rows = [row for row in rows if row["text"]]
        if not rows:
            raise ValueError("No readable report text found. Review the scan or use handwriting transcription.")
        return rows
    raise ValueError("Document must be a .txt, .eml, or .pdf file")
