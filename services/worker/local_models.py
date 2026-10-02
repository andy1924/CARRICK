"""Local inference transport. Models must be provisioned before offline use."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse


def ollama_url() -> str:
    value = os.environ.get("CARRICK_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.path:
        raise ValueError("The offline model endpoint must be an HTTP loopback address")
    return value


def ollama_request(endpoint: str, payload: dict | None = None, timeout: int = 180) -> dict:
    request = urllib.request.Request(
        ollama_url() + endpoint,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        # Loopback inference must not be routed through a configured network proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("The local model could not be reached. Start Ollama and provision the configured models.") from exc
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError("The local model returned an error")
    return result


def installed_models() -> set[str]:
    return {item["name"] for item in ollama_request("/api/tags", timeout=3).get("models", [])
            if "name" in item and not item.get("remote_host") and not item.get("remote_model")
            and "cloud" not in item["name"].lower()}


def model_installed(model: str, names: set[str]) -> bool:
    return bool(model) and "cloud" not in model.lower() and (model in names or (":" not in model and model + ":latest" in names))
