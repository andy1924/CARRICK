"""Conservative report identity and review-only similarity suggestions."""

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def identity(rows: list[dict], capture_day: str) -> tuple[str, str, str]:
    def exact(value):
        return re.sub(r"\s+"," ",unicodedata.normalize("NFC",value)).strip()
    # Preserve letter case: imported TASK codes and engineering units may differ
    # only by case. Case folding is appropriate only for review-only similarity.
    context = [{"text": exact(row["text"]), "date": row.get("event_date") or capture_day,
                "discipline": exact(row.get("discipline") or ""), "location": exact(row.get("location") or "")}
               for row in rows]
    # Dates and negations stay intact; no fuzzy match is eligible for suppression.
    canonical = json.dumps(context, sort_keys=True, ensure_ascii=False)
    metadata = json.dumps([{k: v for k, v in row.items() if k != "text"} for row in context], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest(), normalize(" ".join(row["text"] for row in rows)), metadata


def similar_reports(text: str, context: str, reports: list[dict]) -> list[dict]:
    # Bound quadratic sequence comparison; exact identity still supports large files.
    if len(text) > 20_000:
        return []
    words = set(re.findall(r"\w+", text))
    output = []
    for report in reports:
        if report.get("identity_context") != context or not report.get("normalized_text"):
            continue
        other = report["normalized_text"]
        if len(other) > 20_000:
            continue
        other_words = set(re.findall(r"\w+", other))
        overlap = len(words & other_words) / max(1, len(words | other_words))
        if overlap < .8:
            continue
        similarity = SequenceMatcher(None, text, other, autojunk=False).ratio()
        if similarity >= .9:
            output.append({"report_id": report["id"], "similarity": round(similarity, 3),
                           "reason": "Similar wording and report context; verify before treating it as a repeat"})
    return sorted(output, key=lambda item: -item["similarity"])[:5]
