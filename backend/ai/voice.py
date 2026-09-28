"""Voice role: a character's words, and (in conversation) what they do.

In conversation (converse, D-44) this role says what the person would say, from their character sheet
(persona.py), what they know, why they're here, Jev's reading of the moment and the conversation so far,
and picks one move from those code offers. Code checks the move and applies it; free text never flows
back into world state. speak() puts an already decided reply into words (the older path, still used
when a reply is fixed in advance). The same role keeps memory prose (recollect: a finished conversation becomes an
episode, D-36) and phrases two villagers talking to each other (chatter, D-37). If the model is
unavailable, the person says an authored fallback line instead and memory is kept from the notes.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

from . import config

PROMPT_VERSION = "voice_v3"
_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
_PROMPT = (_PROMPTS / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
CONVERSE_VERSION = "voice_v4"
_CONVERSE = (_PROMPTS / f"{CONVERSE_VERSION}.txt").read_text(encoding="utf-8")
_RECOLLECT = (_PROMPTS / "recollect_v1.txt").read_text(encoding="utf-8")
_CHATTER = (_PROMPTS / "chatter_v1.txt").read_text(encoding="utf-8")
MAX_CHARS = 360


class DialogueLine(BaseModel):
    text: str
    remember: str
    stranger_name: str


class Reply(BaseModel):
    text: str
    move: str  # One key from moves_they_may_make.
    remember: str
    stranger_name: str


class Episode(BaseModel):
    episode: str
    long_memory: str


class Chatter(BaseModel):
    first_line: str
    reply_line: str


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
    remember: str = ""  # What the person will remember of this exchange (D-36).
    stranger_name: str = ""  # A name the stranger gave, if any (code checks it against their words).
    move: str = ""  # What the person does (converse): code checks it against the moves it offered.

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


def _parse(prompt: str, context: dict, schema: type[BaseModel], version: str) -> tuple[VoiceCall, BaseModel | None]:
    """One structured call to the voice model; the call record says how it went."""
    model = config.voice_model()
    call = VoiceCall(status="fallback", text="", model=model, prompt_version=version)
    started = time.perf_counter()
    parsed = None
    try:
        response = config.client().responses.parse(
            model=model, reasoning={"effort": config.voice_reasoning()}, store=False, text_format=schema,
            input=[{"role": "developer", "content": prompt},
                   {"role": "user", "content": json.dumps(context, indent=1, ensure_ascii=False)}])
    except Exception as error:  # The caller keeps going with its fallback.
        call.error = f"{type(error).__name__}: {error}"
    else:
        if response.usage is not None:
            call.input_tokens, call.output_tokens = response.usage.input_tokens, response.usage.output_tokens
        parsed = response.output_parsed
        if parsed is None:
            call.error = "The model returned nothing usable."
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call, parsed


def _unavailable(fallback: str, allowed: bool, version: str) -> VoiceCall | None:
    if not allowed:
        return VoiceCall(status="fallback", text=fallback, prompt_version=version,
                         error="Model call allowance for this journey is used up.")
    if config.mode() != "live":
        return VoiceCall(status="fallback", text=fallback, model="stub" if config.mode() == "stub" else None,
                         prompt_version=version,
                         error=None if config.mode() == "stub" else "No OPENAI_API_KEY in backend/.env.")
    return None


def speak(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """The person's line for the decided reply (and their note of it); the fallback line if the model can't be used."""
    skipped = _unavailable(fallback, allowed, PROMPT_VERSION)
    if skipped:
        return skipped
    call, parsed = _parse(_PROMPT, context, DialogueLine, PROMPT_VERSION)
    call.text = fallback
    spoken = tidy(parsed.text) if parsed is not None else ""
    if spoken:
        call.status, call.text = "ok", spoken
        call.remember = " ".join(parsed.remember.split())[:300]
        call.stranger_name = " ".join(parsed.stranger_name.split())[:40]
    elif call.error is None:
        call.error = "The model returned no line."
    return call


def converse(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """What the person says and does back (D-44); the fallback line (and no move) if the model can't be used."""
    skipped = _unavailable(fallback, allowed, CONVERSE_VERSION)
    if skipped:
        return skipped
    call, parsed = _parse(_CONVERSE, context, Reply, CONVERSE_VERSION)
    call.text = fallback
    spoken = tidy(parsed.text) if parsed is not None else ""
    if spoken:
        call.status, call.text = "ok", spoken
        call.move = parsed.move.strip()
        call.remember = " ".join(parsed.remember.split())[:300]
        call.stranger_name = " ".join(parsed.stranger_name.split())[:40]
    elif call.error is None:
        call.error = "The model returned no line."
    return call


def converse_prompt() -> str:
    return _CONVERSE


def recollect(context: dict, fallback: dict, allowed: bool = True) -> tuple[VoiceCall, dict]:
    """A finished conversation becomes one remembered episode (and older ones fold into long memory)."""
    skipped = _unavailable("", allowed, "recollect_v1")
    if skipped:
        return skipped, fallback
    call, parsed = _parse(_RECOLLECT, context, Episode, "recollect_v1")
    if parsed is None or not parsed.episode.strip():
        return call, fallback
    call.status = "ok"
    return call, {"episode": " ".join(parsed.episode.split())[:400],
                  "long_memory": " ".join(parsed.long_memory.split())[:600] or fallback["long_memory"]}


def chatter(context: dict, fallback: tuple[str, str], allowed: bool = True) -> tuple[VoiceCall, tuple[str, str]]:
    """Two villagers talking to each other, in their own voices (only when the stranger can hear it)."""
    skipped = _unavailable("", allowed, "chatter_v1")
    if skipped:
        return skipped, fallback
    call, parsed = _parse(_CHATTER, context, Chatter, "chatter_v1")
    if parsed is None or not parsed.first_line.strip() or not parsed.reply_line.strip():
        return call, fallback
    call.status = "ok"
    return call, (tidy(parsed.first_line), tidy(parsed.reply_line))
