"""Runtime AI configuration from backend/.env. Provider keys never leave the backend."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH, override=False)

try:  # Use the operating system's certificate store, matching `uv --native-tls`.
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def mode() -> str:
    """'live' with a key; 'stub' (no model, deterministic test answers) when AI_MODE=stub; else 'off'."""
    requested = _env("AI_MODE", "live").lower()
    if requested == "stub":
        return "stub"
    return "live" if api_key() and requested != "off" else "off"


def judge_model() -> str:
    return _env("MODEL_JUDGE", "gpt-6-sol")


def judge_reasoning() -> str:
    return _env("JUDGE_REASONING", "low")


def image_model() -> str:
    return _env("MODEL_IMAGE", "gpt-image-2.5-flare")


def image_fallback_model() -> str:
    return _env("MODEL_IMAGE_FALLBACK", "gpt-image-2")


def image_quality() -> str:
    return _env("IMAGE_QUALITY", "medium")


def max_calls_per_run() -> int:
    return int(_env("MAX_MODEL_CALLS_PER_RUN", "200"))


def judge_enabled() -> bool:
    return mode() in ("live", "stub")


def images_enabled() -> bool:
    return mode() in ("live", "stub") and _env("IMAGES", "on").lower() != "off"


def status() -> dict:
    return {"mode": mode(), "judge": judge_enabled(), "images": images_enabled(),
            "judge_model": judge_model(), "image_model": image_model()}


@lru_cache(maxsize=1)
def _client(key: str):
    from openai import OpenAI

    return OpenAI(api_key=key, timeout=180.0, max_retries=1)


def client():
    return _client(api_key())
