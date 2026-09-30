"""Voice role: characters' words, and (in conversation) what they do.

In conversation the role writes the group's moment (scene, D-48): the person addressed answers, and others in the
conversation or near enough to hear may add a line, talk to each other or ask the stranger something. Each line
comes from that person's character sheet (persona.py), what they know, why they're there and the conversation so
far; each speaker reads the moment themselves (D-46) and picks one move from those code offers them. Code checks
every line and applies it as that person's exchange; free text never flows back into world state. speak() puts an
already decided reply into words (used by the persona eval). The same role keeps memory prose (recollect: a
finished conversation becomes an episode, D-36) and phrases two villagers talking to each other (chatter, D-37).
If the model is unavailable, the person addressed says an authored fallback line instead.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Literal
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import config

PROMPT_VERSION = "voice_v3"
_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
_PROMPT = (_PROMPTS / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
IMPRESSION = ["Much worse", "A little worse", "Unchanged", "A little better", "Much better"]
SUSPICION = ["Much less suspicious", "A little less suspicious", "Unchanged", "A little more suspicious",
             "Much more suspicious"]
ANGER = ["Calm", "Annoyed", "Angry", "Furious"]
SCENE_VERSION = "scene_v2"  # D-51: errands, promises kept, talk mid-fight.
_SCENE = (_PROMPTS / f"{SCENE_VERSION}.txt").read_text(encoding="utf-8")
SCENE_LINES = 3
DEVICE_VERSION = "device_v1"  # The device from the future, answering the stranger (D-50).
_DEVICE = (_PROMPTS / f"{DEVICE_VERSION}.txt").read_text(encoding="utf-8")
_RECOLLECT = (_PROMPTS / "recollect_v1.txt").read_text(encoding="utf-8")
_CHATTER = (_PROMPTS / "chatter_v1.txt").read_text(encoding="utf-8")
MAX_CHARS = 360


class DeviceLine(BaseModel):
    text: str


class DialogueLine(BaseModel):
    text: str
    remember: str
    stranger_name: str


class SceneLine(BaseModel):
    """One person's line in a group moment: who speaks, what they say and do, how they read it (D-48)."""
    speaker_id: str
    text: str
    move: str
    impression: Literal["Much worse", "A little worse", "Unchanged", "A little better", "Much better"]
    suspicion: Literal["Much less suspicious", "A little less suspicious", "Unchanged", "A little more suspicious",
                       "Much more suspicious"]
    anger: Literal["Calm", "Annoyed", "Angry", "Furious"]
    believes_what_was_said: bool
    sees_the_stranger_as_a_threat: bool
    reason_enough_to_let_them_through: bool
    agreed_to_the_deal: bool
    did_what_was_asked: bool
    errand_to: str
    errand_message: str
    promised_later: str
    remember: str


class Scene(BaseModel):
    lines: list[SceneLine]
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
    answers: dict = field(default_factory=dict)  # Their reading of the moment, in the typed-answer shape code uses.
    lines: list = field(default_factory=list)  # A group moment (scene): [{speaker_id, text, move, answers, remember}].

    def as_dict(self) -> dict:
        return asdict(self)


def system_prompt() -> str:
    """The prompt the game's conversations use (the group scene, D-48)."""
    return _SCENE


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
    response = None
    for attempt in range(2):  # One retry when the model's output doesn't match the schema (it happens rarely).
        try:
            response = config.client().responses.parse(
                model=model, reasoning={"effort": config.voice_reasoning()}, store=False, text_format=schema,
                input=[{"role": "developer", "content": prompt},
                       {"role": "user", "content": json.dumps(context, indent=1, ensure_ascii=False)}])
            call.error = None
            break
        except ValidationError as error:  # Malformed structured output: keep a whole answer followed by stray text,
            call.error = f"{type(error).__name__}: {error}"  # or ask once more.
            parsed = salvage(error, schema)
            if parsed is not None:
                call.error = None
                break
        except Exception as error:  # Anything else: the caller keeps going with its fallback.
            call.error = f"{type(error).__name__}: {error}"
            break
    if response is not None and call.error is None and parsed is None:
        if response.usage is not None:
            call.input_tokens, call.output_tokens = response.usage.input_tokens, response.usage.output_tokens
        parsed = response.output_parsed
        if parsed is None:
            call.error = "The model returned nothing usable."
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call, parsed


def salvage(error: ValidationError, schema: type[BaseModel]) -> BaseModel | None:
    """A complete, valid answer with stray text after it ("trailing characters", seen live twice in a row): keep
    the answer. Anything else malformed stays an error."""
    raw = next((e.get("input") for e in error.errors() if e.get("type") == "json_invalid"), None)
    if not isinstance(raw, str):
        return None
    try:
        whole, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        return schema.model_validate(whole)
    except (ValueError, ValidationError):
        return None


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


def reading(parsed: SceneLine) -> dict:
    """The person's reading of the moment, in the typed-answer shape the rest of the code reads."""
    yes = lambda value: {"type": "noul", "noul": 0.9 if value else 0.1}  # noqa: E731
    return {"impression": {"type": "score", "score": IMPRESSION.index(parsed.impression)},
            "suspicion": {"type": "score", "score": SUSPICION.index(parsed.suspicion)},
            "anger": {"type": "score", "score": ANGER.index(parsed.anger)},
            "believes": yes(parsed.believes_what_was_said), "threat": yes(parsed.sees_the_stranger_as_a_threat),
            "reason": yes(parsed.reason_enough_to_let_them_through), "accepts": yes(parsed.agreed_to_the_deal),
            "done": yes(parsed.did_what_was_asked)}


def scene(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """A group moment (D-48): up to three lines, in order, each by a person in or near the conversation, with
    what they do and how they read it. Code checks every line. If the model can't be used: no lines (the caller
    has the addressed person say the authored fallback)."""
    skipped = _unavailable(fallback, allowed, SCENE_VERSION)
    if skipped:
        return skipped
    call, parsed = _parse(_SCENE, context, Scene, SCENE_VERSION)
    call.text = fallback
    lines = []
    for line in (parsed.lines if parsed is not None else [])[:SCENE_LINES]:
        spoken = tidy(line.text)
        if spoken:
            lines.append({"speaker_id": line.speaker_id.strip(), "text": spoken, "move": line.move.strip(),
                          "answers": reading(line), "remember": " ".join(line.remember.split())[:300],
                          "errand_to": line.errand_to.strip()[:60],
                          "errand_message": " ".join(line.errand_message.split())[:240],
                          "promised_later": " ".join(line.promised_later.split())[:240]})
    if lines:
        call.status, call.lines, call.text = "ok", lines, lines[0]["text"]
        call.stranger_name = " ".join(parsed.stranger_name.split())[:40]
    elif call.error is None:
        call.error = "The model returned no lines."
    return call


def device(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """The device answers the stranger's question (D-50); its written hint if the model can't be asked."""
    skipped = _unavailable(fallback, allowed, DEVICE_VERSION)
    if skipped:
        return skipped
    call, parsed = _parse(_DEVICE, context, DeviceLine, DEVICE_VERSION)
    call.text = fallback
    spoken = " ".join(parsed.text.split())[:500] if parsed is not None else ""
    if spoken:
        call.status, call.text = "ok", spoken
    elif call.error is None:
        call.error = "The model returned no line."
    return call


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
