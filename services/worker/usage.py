"""Content-free model accounting. Missing usage or prices remain unknown."""
import contextvars
import math
from datetime import date

active_calls = contextvars.ContextVar("carrick_model_calls", default=None)


def record(calls, provider, model, endpoint, milliseconds, response=None, failed=False):
    response = response or {}
    usage = response.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", response.get("prompt_eval_count")))
    output_tokens = usage.get("output_tokens", response.get("eval_count", 0 if endpoint.endswith("embed") or endpoint.endswith("embeddings") else None))
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    def count(value):
        return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
    input_tokens,output_tokens = count(input_tokens),count(output_tokens)
    cached = count(cached)
    entry = {"provider": provider, "model": model, "endpoint": endpoint, "latency_ms": round(milliseconds, 2),
             "input_tokens": input_tokens, "output_tokens": output_tokens, "cached_tokens": cached, "failed": failed}
    calls.append(entry)
    if active_calls.get() is not None:
        active_calls.get().append(entry)


def estimate_cost(calls, rates):
    if not calls: return 0.0
    if not rates or not rates.get("as_of") or not rates.get("source") or rates.get("currency") != "USD":
        return None
    try: date.fromisoformat(rates["as_of"])
    except (ValueError,TypeError): return None
    total = 0.0
    for call in calls:
        price = rates.get("models", {}).get(call["model"])
        if call["provider"] != "openai" or call["failed"] or not price or call["input_tokens"] is None or call["output_tokens"] is None:
            return None
        if call["cached_tokens"] is None: return None
        cached = min(call["cached_tokens"], call["input_tokens"])
        if cached and "cached_input_per_million" not in price:
            return None
        try:
            values = [float(price.get("input_per_million", -1)), float(price.get("output_per_million", -1)), float(price.get("cached_input_per_million", 0))]
            if any(not math.isfinite(v) or v < 0 for v in values): return None
            total += ((call["input_tokens"] - cached) * values[0] + cached * values[2] + call["output_tokens"] * values[1]) / 1_000_000
        except (TypeError, ValueError):
            return None
    return round(total, 8)
