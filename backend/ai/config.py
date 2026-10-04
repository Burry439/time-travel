"""Runtime AI configuration from backend/.env. Provider keys never leave the backend."""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH, override=False)
# Some Windows network monitors set SSLKEYLOGFILE to a pipe this process may not open; every TLS context then
# fails with PermissionError (the 28 Sep "500 on talk"). Key logging is for debugging captures, never needed here.
os.environ.pop("SSLKEYLOGFILE", None)

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
    return _env("MODEL_JUDGE", "gpt-6-luna")


def judge_reasoning() -> str:
    return _env("JUDGE_REASONING", "low")


def voice_model() -> str:
    return _env("MODEL_VOICE", "gpt-6-luna")


def voice_reasoning() -> str:
    return _env(
        "VOICE_REASONING", "low"
    )  # Each person decides as well as speaks (D-62), so they get a moment's thought.


def image_model() -> str:
    return _env("MODEL_IMAGE", "gpt-image-2.5-flare")


def image_fallback_model() -> str:
    return _env("MODEL_IMAGE_FALLBACK", "gpt-image-2")


def image_quality() -> str:
    return _env("IMAGE_QUALITY", "medium")


def max_calls_per_run() -> int:
    return int(_env("MAX_MODEL_CALLS_PER_RUN", "200"))


def max_decider_calls_per_run() -> int:
    """People deciding their day and their chats (about $0.0001 each); reactions to the stranger always go ahead."""
    return int(_env("MAX_DECIDER_CALLS_PER_RUN", "1500"))


def judge_enabled() -> bool:
    return mode() in ("live", "stub")


def images_enabled() -> bool:
    return mode() in ("live", "stub") and _env("IMAGES", "on").lower() != "off"


def status() -> dict:
    return {
        "mode": mode(),
        "judge": judge_enabled(),
        "images": images_enabled(),
        "judge_model": judge_model(),
        "voice_model": voice_model(),
        "image_model": image_model(),
    }


# Each request's model calls share one budget (D-62), retries and reconsideration included. Speech: the person
# addressed, then everyone else there in parallel. D-63: 12 s, measured at the gate (captain plus two guards, live):
# 8 s cut off 7 of 30 people's calls (their turn, and any silent decision in it, lost); 12 s cut 1 of 30, and the
# median round barely moved (7.2 s against 8.0 s): the budget is a ceiling, not a wait.
SPEECH_BUDGET_S = 12.0
DEED_BUDGET_S = 15.0  # A Try Something: the judge, one bounded reconsideration and the reply.


@lru_cache(maxsize=1)
def _client(key: str):
    from openai import OpenAI

    return OpenAI(api_key=key, timeout=SPEECH_BUDGET_S, max_retries=0)


deadline = ContextVar("model_request_deadline", default=None)


def remaining() -> float:
    end = deadline.get()
    return max(0.0, end - time.monotonic()) if end is not None else SPEECH_BUDGET_S


def client():
    seconds = remaining()
    if seconds <= 0.05:
        raise TimeoutError("The request's model budget is exhausted.")
    return _client(api_key()).with_options(timeout=seconds, max_retries=0)


def image_client():
    return _client(api_key()).with_options(timeout=180.0, max_retries=1)


@lru_cache(maxsize=1)
def credential_readiness(key: str, model: str) -> dict:
    if mode() == "stub":
        return {"ready": True, "mode": "stub", "reason": None}
    if not key or mode() != "live":
        return {"ready": False, "mode": mode(), "reason": "missing_configuration"}
    try:
        _client(key).with_options(timeout=5.0, max_retries=0).models.retrieve(model)
        return {"ready": True, "mode": "live", "reason": None}
    except Exception as error:
        code = getattr(error, "status_code", None)
        reason = (
            "invalid_or_expired_key"
            if code == 401
            else "model_unavailable"
            if code in (403, 404)
            else "provider_unreachable"
        )
        return {"ready": False, "mode": "live", "reason": reason}
