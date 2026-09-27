"""Voice role: puts a decision that has already been made into a character's words.

The decider (Jev) chooses what a person does in a conversation; this role only phrases it,
from the person's card, what they know, and the conversation so far. Free text never flows
back into world state: code applies the decision, and the line is what the player reads.
If the model is unavailable, the person says an authored fallback line instead.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

from . import config

PROMPT_VERSION = "voice_v1"
_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
MAX_CHARS = 360


class DialogueLine(BaseModel):
    text: str


@dataclass
class VoiceCall:
    status: str  # "ok", "fallback" (no model, capped or failed: the authored line was used)
    text: str
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def system_prompt() -> str:
    return _PROMPT


def tidy(text: str) -> str:
    """One to three sentences of speech, without wrapping quotes or a name label."""
    text = " ".join(text.split()).strip().strip('"“”').strip()
    text = re.sub(r"^[A-Z][a-z]+:\s+", "", text)
    sentences = re.findall(r"[^.!?]+[.!?]+[\"”’]?|[^.!?]+$", text)
    text = " ".join(s.strip() for s in sentences[:3]).strip()
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"


def speak(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """The person's line for the decided reply; the fallback line whenever the model can't be used."""
    if not allowed:
        return VoiceCall(status="fallback", text=fallback, error="Model call allowance for this journey is used up.")
    if config.mode() != "live":
        return VoiceCall(status="fallback", text=fallback, model="stub" if config.mode() == "stub" else None,
                         error=None if config.mode() == "stub" else "No OPENAI_API_KEY in backend/.env.")
    model = config.voice_model()
    call = VoiceCall(status="fallback", text=fallback, model=model)
    started = time.perf_counter()
    try:
        response = config.client().responses.parse(
            model=model, reasoning={"effort": config.voice_reasoning()}, store=False, text_format=DialogueLine,
            input=[{"role": "developer", "content": _PROMPT},
                   {"role": "user", "content": json.dumps(context, indent=1, ensure_ascii=False)}])
    except Exception as error:  # The authored line keeps the conversation going.
        call.error = f"{type(error).__name__}: {error}"
    else:
        if response.usage is not None:
            call.input_tokens, call.output_tokens = response.usage.input_tokens, response.usage.output_tokens
        parsed = response.output_parsed
        spoken = tidy(parsed.text) if parsed is not None else ""
        if spoken:
            call.status, call.text = "ok", spoken
        else:
            call.error = "The model returned no line."
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call
