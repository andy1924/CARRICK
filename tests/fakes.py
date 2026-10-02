"""Deterministic providers used only by isolated test servers and tests."""
from services.worker.ai import AiResponseError

class FakeAIClient:
    embedding_model="fake-embedding"
    model="fake-structured-model"
    def __init__(self): self.calls=[]
    def embed(self,texts): return [[float("north" in text.lower()),float("pump" in text.lower()),1.0] for text in texts]
    def structured(self,name,instructions,data,schema):
        if name=="field_events":
            if "PROVIDER_DOWN" in data["report"]: raise AiResponseError("Mock provider is unavailable")
            return {"events":[{"quote":data["report"],"kind":"actual_start","event_date":"2026-10-01","discipline":"piping","location":""}]}
        if "Clarification from site: north" in data["field_event"]:
            return {"ranked_ids":["NEW-999","PI-301","PI-302"],"ambiguous":False,"reason":"North matches the pipeline location","clarification_question":""}
        return {"ranked_ids":["NEW-999","PI-301","PI-302"],"ambiguous":True,"reason":"Both pipeline welds fit the note","clarification_question":"North or south pipeline?"}

def document(filename,content,handwriting=False):
    if filename.startswith("unavailable"): raise ValueError("Mock OCR is unavailable; original scan retained")
    return [{"text":"North pipeline welding started today","source_row":1,"method":"tesseract","confidence":91,"warnings":[]}]

def speech(filename,content,language=""):
    if filename.startswith("unavailable"): raise ValueError("Mock speech is unavailable")
    return {"text":"South pipeline welding started today","warnings":[],"language":"en","duration_seconds":1}
