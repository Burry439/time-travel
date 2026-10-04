"""Voice role: characters' words, and (in conversation) what they do.

Each person is their own agent (D-60). In conversation the person addressed answers in a call of their own, which
holds only their own sheet (persona.py), memory, knowledge and secrets, what anyone there could see and hear, and the
rules that apply to them: a short core (person_v2) plus a module for each thing they are (a guard, a robber), have
(an open deal, a story beat, a secret they could confide, something a story lets them agree to) or are in (a fight,
a group). Then everyone else there decides, each in their own call and in parallel, whether to say something, having
heard that answer. Each reads the moment themselves (D-46) and picks one move from those code offers them; code
checks every line and applies it as that person's exchange. Free text never flows back into world state. Beside the
conversation, a separate reading says whether the stranger's words passed on a secret they were told (told, D-61),
so no one's own call ever holds anyone else's secrets. The same role keeps memory prose (recollect, D-36), phrases
two villagers talking (chatter, D-37: each side in its own call) and someone coming to tell someone something
(hearing, D-54: each side in its own call). If the model is unavailable, the person addressed says an authored
fallback line.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from . import config

_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
IMPRESSION = ["Much worse", "A little worse", "Unchanged", "A little better", "Much better"]
SUSPICION = [
    "Much less suspicious",
    "A little less suspicious",
    "Unchanged",
    "A little more suspicious",
    "Much more suspicious",
]
ANGER = ["Calm", "Annoyed", "Angry", "Furious"]
# D-60: each person their own agent, a core and the rules that apply to them. v2 (D-61): secrets confided and story
# moves. v3 (D-62): one decision contract for talk, reactions, news and plans. v4 (D-63): a feared wonder explained.
PERSON_VERSION = "person_v4"
SCENE_LINES = 3
WEIGHTY_REASONING = "low"  # For a person's call that carries a secret they could tell or a story move (D-61).


def _modules(text: str) -> dict[str, str]:
    """The person prompt's parts, each under a line "=== name ===": the core, and the rules only some people need."""
    parts = re.split(r"^=== (\w+) ===\n", text, flags=re.M)
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}


MODULES = _modules((_PROMPTS / f"{PERSON_VERSION}.txt").read_text(encoding="utf-8"))
DEVICE_VERSION = "device_v2"  # The device from the future (D-50); a coach with a memory (D-55).
_DEVICE = (_PROMPTS / f"{DEVICE_VERSION}.txt").read_text(encoding="utf-8")
_RECOLLECT = (_PROMPTS / "recollect_v1.txt").read_text(encoding="utf-8")
CHATTER_VERSION = "chatter_v2"  # D-59: each side of a chat in its own call.
CHATTER = _modules((_PROMPTS / f"{CHATTER_VERSION}.txt").read_text(encoding="utf-8"))
HEARING_VERSION = "hearing_v2"  # Someone comes to tell someone something; the listener decides (D-54). v2: each in their own call (D-59).
HEARING = _modules((_PROMPTS / f"{HEARING_VERSION}.txt").read_text(encoding="utf-8"))
TOLD_VERSION = "told_v1"  # Whether the stranger's words passed on a secret they were told (D-61).
_TOLD = (_PROMPTS / f"{TOLD_VERSION}.txt").read_text(encoding="utf-8")
MAX_CHARS = 360


class DeviceLine(BaseModel):
    text: str


class FeelingShift(BaseModel):
    """How a speaker's feelings toward someone else changed in this moment (D-59)."""

    person_id: str
    change: Literal["Much worse", "A little worse", "A little better", "Much better"]


class NpcIntent(BaseModel):
    kind: Literal["help", "give", "lend", "vouch", "admit", "go", "physical"]
    object_ids: list[str]
    goal: list[int]
    task: str


class NegotiatedAgreement(BaseModel):
    action: Literal["offer", "accept", "satisfied"]
    agreement_id: str
    task: str
    check: str
    rewards: list[NpcIntent]
    evidence_ids: list[str]


class PersonLine(BaseModel):
    """One person's turn in a moment of conversation, written by their own call (D-59): whether they speak, what
    they say and do, how they read it."""

    respect: Literal["Much worse", "A little worse", "Unchanged", "A little better", "Much better"] = "Unchanged"
    awe: Literal["Much worse", "A little worse", "Unchanged", "A little better", "Much better"] = "Unchanged"
    fear: Literal["Not afraid", "Uneasy", "Afraid", "Terrified"] = "Not afraid"
    understood_the_wonder: bool = False  # A feared wonder, explained, made sense to them (D-63).
    intents: list[NpcIntent] = []
    agreement: NegotiatedAgreement | None = None
    defend_if_attacked: bool = False
    speaks: bool
    text: str
    brought_up_story_beat: bool  # The line gets the speaker's story beat across (D-59).
    move: str
    impression: Literal["Much worse", "A little worse", "Unchanged", "A little better", "Much better"]
    suspicion: Literal[
        "Much less suspicious",
        "A little less suspicious",
        "Unchanged",
        "A little more suspicious",
        "Much more suspicious",
    ]
    anger: Literal["Calm", "Annoyed", "Angry", "Furious"]
    believes_what_was_said: bool
    sees_the_stranger_as_a_threat: bool
    reason_enough_to_let_them_through: bool
    agreed_to_the_deal: bool
    did_what_was_asked: bool
    feelings_toward_others: list[FeelingShift]
    errand_to: str
    errand_message: str
    promised_later: str
    remember: str
    stranger_name: str


class Episode(BaseModel):
    episode: str
    long_memory: str


class Told(BaseModel):
    passed_on: list[str]


class Said(BaseModel):
    line: str


class Heard(BaseModel):
    line: str
    move: str
    pass_on_message: str
    remember: str


@dataclass
class VoiceCall:
    status: str  # "ok", "fallback" (no model, capped or failed: the authored line was used)
    text: str
    model: str | None = None
    prompt_version: str = PERSON_VERSION
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    remember: str = ""  # What the person will remember of this exchange (D-36).
    stranger_name: str = ""  # A name the stranger gave, if any (code checks it against their words).
    answers: dict = field(default_factory=dict)  # Their reading of the moment, in the typed-answer shape code uses.
    lines: list = field(default_factory=list)  # A group moment (scene): [{speaker_id, text, move, answers, remember}].
    decisions: list = field(default_factory=list)  # Silent NPC decisions still apply, without dialogue.
    turns: list = field(default_factory=list)  # Each person's own call in a moment: [{speaker_id, status, ms, tokens}].

    def as_dict(self) -> dict:
        return asdict(self)


def system_prompt() -> str:
    """The core of every person's prompt in conversation (D-59: the rules some people need are added to theirs)."""
    return MODULES["core"]


def tidy(text: str) -> str:
    """One to three sentences of speech, without wrapping quotes or a name label."""
    text = " ".join(text.split()).strip().strip('"“”').strip()
    text = re.sub(r"^[A-Z][a-z]+:\s+", "", text)
    sentences = re.findall(r"[^.!?]+[.!?]+[\"”’]?|[^.!?]+$", text)
    text = " ".join(s.strip() for s in sentences[:3]).strip()
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"


def _parse(
    prompt: str, context: dict, schema: type[BaseModel], version: str, reasoning: str | None = None
) -> tuple[VoiceCall, BaseModel | None]:
    """One structured call to the voice model; the call record says how it went. reasoning overrides the role's
    (VOICE_REASONING) for a call that carries a weighty decision."""
    model = config.voice_model()
    call = VoiceCall(status="fallback", text="", model=model, prompt_version=version)
    started = time.perf_counter()
    parsed = None
    response = None
    for _attempt in range(2):  # One retry when the model's output doesn't match the schema (it happens rarely).
        try:
            response = config.client().responses.parse(
                model=model,
                reasoning={"effort": reasoning or config.voice_reasoning()},
                store=False,
                text_format=schema,
                input=[
                    {"role": "developer", "content": prompt},
                    {"role": "user", "content": json.dumps(context, indent=1, ensure_ascii=False)},
                ],
            )
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
        return VoiceCall(
            status="fallback",
            text=fallback,
            prompt_version=version,
            error="Model call allowance for this journey is used up.",
        )
    if config.mode() != "live":
        return VoiceCall(
            status="fallback",
            text=fallback,
            model="stub" if config.mode() == "stub" else None,
            prompt_version=version,
            error=None if config.mode() == "stub" else "No OPENAI_API_KEY in backend/.env.",
        )
    return None


def reading(parsed: PersonLine) -> dict:
    """The person's reading of the moment, in the typed-answer shape the rest of the code reads."""
    yes = lambda value: {"type": "noul", "noul": 0.9 if value else 0.1}  # noqa: E731
    return {
        "impression": {"type": "score", "score": IMPRESSION.index(parsed.impression)},
        "suspicion": {"type": "score", "score": SUSPICION.index(parsed.suspicion)},
        "anger": {"type": "score", "score": ANGER.index(parsed.anger)},
        "fear": {"type": "score", "score": ["Not afraid", "Uneasy", "Afraid", "Terrified"].index(parsed.fear) / 3},
        "respect": {"type": "score", "score": IMPRESSION.index(parsed.respect)},
        "awe": {"type": "score", "score": IMPRESSION.index(parsed.awe)},
        "believes": yes(parsed.believes_what_was_said),
        "threat": yes(parsed.sees_the_stranger_as_a_threat),
        "reason": yes(parsed.reason_enough_to_let_them_through),
        "accepts": yes(parsed.agreed_to_the_deal),
        "done": yes(parsed.did_what_was_asked),
        "understood": yes(parsed.understood_the_wonder),
    }


def scene(context: dict, fallback: str, allowed: bool = True) -> VoiceCall:
    """A moment of conversation, one person at a time (D-59: each person is their own agent). The person addressed
    answers in their own call, which holds only their own sheet, memory and knowledge and what anyone could see and
    hear; then everyone else here decides in a call of their own, in parallel, whether to say something, having heard
    that answer. Nobody's sheet or secrets are ever in anyone else's call. Up to three lines, addressed first. If the
    model can't be used: no lines (the caller has the addressed person say the authored fallback)."""
    skipped = _unavailable(fallback, allowed, PERSON_VERSION)
    if skipped:
        return skipped
    people = context["people"]
    shared = {key: value for key, value in context.items() if key != "people"}
    started = time.perf_counter()
    first_call, first = _turn(shared, people[0], people, [])
    turns = [(people[0], first_call)]
    lines = [first] if first else []
    if first and len(people) > 1:
        heard = [f"{people[0]['name']}: \u201c{first['text']}\u201d"]
        with ThreadPoolExecutor(max_workers=len(people) - 1) as pool:
            futures = [pool.submit(copy_context().run, _turn, shared, person, people, heard) for person in people[1:]]
            others = [f.result() for f in futures]
        turns += list(zip(people[1:], (call for call, _ in others)))
        spoken_count = 1
        for _, line in others:
            if line is None:
                continue
            if line["speaks"] and spoken_count >= SCENE_LINES:
                line["speaks"] = False
            spoken_count += int(line["speaks"])
            lines.append(line)
    result = VoiceCall(status="fallback", text=fallback, model=first_call.model, prompt_version=PERSON_VERSION)
    result.latency_ms = round((time.perf_counter() - started) * 1000)
    result.input_tokens = sum(call.input_tokens for _, call in turns)
    result.output_tokens = sum(call.output_tokens for _, call in turns)
    result.turns = [
        {"speaker_id": person["id"], "status": call.status, "ms": call.latency_ms, "tokens": call.input_tokens}
        for person, call in turns
    ]
    if first:
        result.status, result.text = "ok", first["text"]
        result.lines = [line for line in lines if line.get("speaks", True)]
        result.decisions = [line for line in lines if not line.get("speaks", True)]
        result.stranger_name = first.pop("stranger_name")
        for line in lines[1:]:
            line.pop("stranger_name", None)
    else:
        result.error = first_call.error or "The model returned no line."
    return result


def _turn(shared: dict, person: dict, people: list[dict], heard: list[str]) -> tuple[VoiceCall, dict | None]:
    """One person's own call: their sheet, what anyone here could see and hear, and the rules that apply to them."""
    you = {key: value for key, value in person.items() if not key.startswith("_") and key != "in_the_conversation"}
    rules = ["core", *person.get("_rules", [])]
    if shared.get("fight_now") and shared["fight_now"] != "No one is fighting.":
        rules.append("fight")
    if len(people) > 1:
        rules.append("feelings")
    payload = {
        "your_part": person["in_the_conversation"],
        **{key: value for key, value in shared.items() if key != "fight_now" or "fight" in rules},
        "said_just_now": heard,
        "others_here": [
            {"id": other["id"], "name": other["name"], "where": other["in_the_conversation"]}
            for other in people
            if other is not person
        ],
        "you": you,
    }
    prompt = "\n\n".join(MODULES[rule] for rule in rules)
    # A secret they could confide or something a story lets them agree to is a decision to weigh, not just a line to
    # phrase: those calls get a moment's thought (D-61: with none, a merchant handed his price still said no).
    weighty = WEIGHTY_REASONING
    call, parsed = _parse(prompt, payload, PersonLine, PERSON_VERSION, weighty)
    if parsed is None:
        return call, None
    call.status = "ok"
    spoken = tidy(parsed.text)
    speaks = parsed.speaks or person["in_the_conversation"] == "addressed"
    if speaks and not spoken:
        return call, None
    return call, {
        "speaker_id": person["id"],
        "speaks": speaks,
        "intents": [i.model_dump() for i in parsed.intents],
        "agreement": parsed.agreement.model_dump() if parsed.agreement else None,
        "defend_if_attacked": parsed.defend_if_attacked,
        "text": spoken,
        "move": parsed.move.strip(),
        "story_beat": parsed.brought_up_story_beat,
        "answers": reading(parsed),
        "remember": " ".join(parsed.remember.split())[:300],
        "errand_to": parsed.errand_to.strip()[:60],
        "errand_message": " ".join(parsed.errand_message.split())[:240],
        "promised_later": " ".join(parsed.promised_later.split())[:240],
        "feelings": [
            {"person_id": f.person_id.strip()[:60], "change": f.change} for f in parsed.feelings_toward_others[:3]
        ],
        "stranger_name": " ".join(parsed.stranger_name.split())[:40],
    }


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
    return call, {
        "episode": " ".join(parsed.episode.split())[:400],
        "long_memory": " ".join(parsed.long_memory.split())[:600] or fallback["long_memory"],
    }


def chatter(context: dict, fallback: tuple[str, str], allowed: bool = True) -> tuple[VoiceCall, tuple[str, str]]:
    """Two villagers talking to each other, in their own voices (only when the stranger can hear it): the speaker in
    a call of their own, then the listener in theirs, having heard them (D-59: neither sees the other's sheet)."""
    skipped = _unavailable("", allowed, CHATTER_VERSION)
    if skipped:
        return skipped, fallback
    speaker, listener = context["speaker"], context["listener"]
    start_call, start = _parse(
        CHATTER["start"],
        {"you": speaker, "talking_to": _public(listener), "topic": context["topic"]},
        Said,
        CHATTER_VERSION,
    )
    if start is None or not start.line.strip():
        return start_call, fallback
    opening = tidy(start.line)
    reply_call, reply = _parse(
        CHATTER["reply"],
        {
            "you": listener,
            "talking_to": _public(speaker),
            "they_said": opening,
            "how_you_take_it": context["listener_reaction"],
        },
        Said,
        CHATTER_VERSION,
    )
    call = _both(start_call, reply_call)
    if reply is None or not reply.line.strip():
        return call, (opening, fallback[1])
    call.status = "ok"
    return call, (opening, tidy(reply.line))


def hearing(context: dict, fallback: dict, allowed: bool = True) -> tuple[VoiceCall, dict]:
    """Someone arrives to tell someone something (D-54): the teller says it in a call of their own, then the listener
    answers in theirs and decides what to do about it (one of their options; code checks it). Neither sees the
    other's sheet (D-59). The written fallback: the message, a nod, and carry on."""
    skipped = _unavailable("", allowed, HEARING_VERSION)
    if skipped:
        return skipped, fallback
    teller, listener = context["teller"], context["listener"]
    tell_call, told = _parse(
        HEARING["tell"],
        {"you": teller, "telling": _public(listener), "message": context["message"]},
        Said,
        HEARING_VERSION,
    )
    teller_line = tidy(told.line) if told is not None and told.line.strip() else fallback["teller_line"]
    hear_call, heard = _parse(
        HEARING["hear"],
        {
            "you": listener,
            "told_by": _public(teller),
            "they_said": teller_line,
            "your_options": context["listener_options"],
        },
        Heard,
        HEARING_VERSION,
    )
    call = _both(tell_call, hear_call)
    if heard is None or not heard.line.strip():
        return call, {**fallback, "teller_line": teller_line}
    call.status = "ok"
    return call, {
        "teller_line": teller_line,
        "listener_line": tidy(heard.line),
        "move": heard.move.strip(),
        "pass_on_message": " ".join(heard.pass_on_message.split())[:240],
        "remember": " ".join(heard.remember.split())[:300],
    }


def told(context: dict, allowed: bool = True) -> tuple[VoiceCall, list[str]]:
    """Which of the secrets the stranger knows their words just passed on to the people there (D-61): a reading
    beside the conversation, so nobody's own call holds anyone else's secrets. Only ids offered come back; none
    when the model can't be used."""
    skipped = _unavailable("", allowed, TOLD_VERSION)
    if skipped:
        return skipped, []
    call, parsed = _parse(_TOLD, context, Told, TOLD_VERSION)
    if parsed is None:
        return call, []
    call.status = "ok"
    offered = {item["id"] for item in context["could_pass_on"]}
    return call, [i for i in dict.fromkeys(parsed.passed_on) if i in offered]


def _public(person: dict) -> dict:
    """What anyone can see of someone else: their name and what they do. Never their sheet."""
    return {"name": person["name"], "role": person.get("role", "")}


def _both(first: VoiceCall, second: VoiceCall) -> VoiceCall:
    """Two people's calls as one record: their time and tokens together."""
    first.latency_ms += second.latency_ms
    first.input_tokens += second.input_tokens
    first.output_tokens += second.output_tokens
    first.error = first.error or second.error
    return first


# The same personal decision contract is used for witnessing and conversation.
NpcDecision = PersonLine


def react(context: dict) -> tuple[VoiceCall, dict | None]:
    if config.mode() != "live":
        return VoiceCall(status="fallback", text="", model="stub"), None
    call, parsed = _parse(MODULES["core"], context, NpcDecision, PERSON_VERSION, WEIGHTY_REASONING)
    if parsed is None:
        return call, None
    call.status = "ok"
    return call, {
        "answers": reading(parsed),
        "move": parsed.move,
        "text": tidy(parsed.text) if parsed.speaks else "",
        "remember": parsed.remember,
        "intents": [i.model_dump() for i in parsed.intents],
        "agreement": parsed.agreement.model_dump() if parsed.agreement else None,
        "defend_if_attacked": parsed.defend_if_attacked,
    }
