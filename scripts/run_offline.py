"""Start Carrick with local inference only; does not install or download models."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from services.worker.ai import load_local_env


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser(description="Run Carrick with a provisioned local Ollama service")
    parser.add_argument("--model", default=os.environ.get("CARRICK_LOCAL_MODEL", ""))
    parser.add_argument("--embedding-model", default=os.environ.get("CARRICK_LOCAL_EMBEDDING_MODEL", ""))
    parser.add_argument("--speech-model", default=os.environ.get("CARRICK_WHISPER_MODEL_PATH", ""))
    parser.add_argument("--vision-model", default=os.environ.get("CARRICK_VISION_MODEL", ""))
    args = parser.parse_args()
    if not args.model or not args.embedding_model:
        parser.error("Set local generation and embedding models in .env or pass --model and --embedding-model")
    if "cloud" in args.model.lower() or "cloud" in args.embedding_model.lower() or "cloud" in args.vision_model.lower():
        parser.error("Offline deployment requires locally installed models, not cloud model names")
    if args.speech_model and not (Path(args.speech_model) / "model.bin").is_file():
        parser.error("The speech model must be a provisioned faster-whisper directory containing model.bin")
    os.environ.update(CARRICK_AI_MODE="ollama", CARRICK_LOCAL_MODEL=args.model,
                      CARRICK_LOCAL_EMBEDDING_MODEL=args.embedding_model,
                      CARRICK_WHISPER_MODEL_PATH=args.speech_model, CARRICK_VISION_MODEL=args.vision_model,
                      CARRICK_HOST="127.0.0.1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # This environment applies to Carrick. Disable cloud separately on the Ollama service.
    from services.api.app import main as serve
    serve()


if __name__ == "__main__":
    main()
