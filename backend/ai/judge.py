"""Physics judge role: turns a Try Something intention plus world context into a proposal.

The proposal is never authoritative; crafting.validate decides what it may change.
Every call returns a JudgeCall with the raw model output for the developer trace.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

import content
import gear

from . import config

PROMPT_VERSION = "judge_v15"
_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")

Flag = Literal[
    "rigid",
    "flexible",
    "sharp_edge",
    "tieable",
    "adhesive",
    "container",
    "watertight",
    "floats",
    "combustible",
    "ferromagnetic",
    "magnetized",
    "magnet_source",
    "light_source",
    "heat_source",
    "sound_loud",
    "reflective",
    "indicates_direction",
    "measures_length",
    "stable_support",
    "fulcrum",
]


class Gear(BaseModel):
    """What a made thing is for, if anything (D-49). Code checks the class against the thing's physics."""

    kind: Literal["weapon", "shield", "armour", "clothing", "ammo", "remedy", "none"]
    gear_class: str  # One class id from gear_classes for that kind, or "" for none.
    covers: list[Literal["head", "neck", "body", "arms", "legs", "hands", "feet"]]
    quality: Literal["crude", "fair", "good"]


class Capability(BaseModel):
    text: str
    status: Literal["expected", "untested"]


class NewObject(BaseModel):
    name: str
    description: str
    materials: list[str]
    consumes: list[str]
    tools_used: list[str]
    mass_kg: float
    length_m: float | None
    capacity_l: float | None
    rated_load_kg: float | None
    flags: list[Flag]
    capabilities: list[Capability]
    gear: Gear | None


class Piece(BaseModel):
    name: str
    description: str
    materials: list[str]
    count: int
    mass_kg: float  # each
    length_m: float | None
    flags: list[Flag]
    capabilities: list[Capability]
    gear: Gear | None


class Transformation(BaseModel):
    target_id: str
    tools_used: list[str]
    result_state: Literal["felled", "cut_up", "broken", "destroyed"]
    pieces: list[Piece]


class Harm(BaseModel):
    target_id: str
    weapon_id: str | None
    method: Literal["melee", "thrown", "poured"]
    family: Literal["blow", "missile", "pour", "choke", "other"]
    outcome: Literal["missed", "blocked", "landed"]
    target_area: Literal["head", "neck", "heart", "torso", "arm", "leg"]
    held_seconds: int  # A choke: how long it is held. Otherwise 0.
    result: Literal["missed", "deflected", "wounded", "knocked_out", "disabled", "killed"]  # Only "other" is taken.
    injury: str


class Treat(BaseModel):
    patient_id: str  # "player" for the stranger, or a person's id.
    remedy_id: str  # The carried thing used to treat it.
    condition: Literal["bleeding", "burn", "broken", "infection"]


class Equip(BaseModel):
    object_id: str
    slot: Literal["right", "left", "head", "body", "arms", "legs", "hands", "feet", "ammo"] | None


class Fill(BaseModel):
    container_id: str
    source_id: str
    litres: float


class Change(BaseModel):
    target_id: str
    temperature: Literal["cold", "warm", "hot", "boiling"] | None
    burning: bool | None
    heat_source_id: str | None
    pour_into_id: str | None
    pour_litres: float | None


class Result(BaseModel):
    text: str
    status: Literal["observed", "failed"]


class Demonstration(BaseModel):
    object_id: str
    used_ids: list[str]
    audience_ids: list[str]
    observed: str  # What an onlooker sees, starting "The stranger".
    works: bool
    capabilities: list[Result]
    wonder: Literal["ordinary", "clever", "uncanny"]  # How it strikes a local onlooker (D-43).


class Give(BaseModel):
    item_ids: list[str]
    recipient_id: str


class Install(BaseModel):
    object_id: str
    into_id: str
    aid_ids: list[str]


class LiftOut(BaseModel):
    object_id: str
    aid_ids: list[str]


class OfferTrade(BaseModel):
    give_ids: list[str]
    want_ids: list[str]
    recipient_id: str


class Gather(BaseModel):
    source_id: str  # The larger thing a small part is taken from; it stays where it is (D-48).
    tools_used: list[str]
    piece: Piece


class Step(BaseModel):
    action: Literal[
        "make",
        "take",
        "gather",
        "transform",
        "harm",
        "fill",
        "change",
        "demonstrate",
        "give",
        "install",
        "lift_out",
        "offer_trade",
        "treat",
        "equip",
        "other",
    ]
    outcome: Literal["success", "failed", "blocked", "unsupported"]
    reason: str
    effort_seconds: int
    new_object: NewObject | None
    take_ids: list[str]
    transformation: Transformation | None
    harm: Harm | None
    fill: Fill | None
    change: Change | None
    demonstration: Demonstration | None
    give: Give | None
    install: Install | None
    lift_out: LiftOut | None
    offer_trade: OfferTrade | None
    gather: Gather | None
    treat: Treat | None
    equip: Equip | None


class JudgeResult(BaseModel):
    clarifying_question: str | None  # When set, nothing is attempted.
    precedent_key: str
    steps: list[Step]  # In order; the engine stops at the first step that does not succeed.


@dataclass
class JudgeCall:
    """Everything about one judge request, successful or not."""

    status: Literal["ok", "disabled", "capped", "error"]
    result: dict | None = None
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    reasoning: str | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    raw_output: str | None = None
    error: str | None = None
    attempt_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def gear_classes() -> dict:
    """The gear classes the judge may name (code owns what each does: data/content/gear.json)."""
    return {
        "weapon": {k: v["name"] for k, v in gear.WEAPONS.items() if k not in ("fists", "improvised")},
        "shield": {k: v["name"] for k, v in gear.SHIELDS.items()},
        "armour": {k: v["name"] for k, v in gear.ARMOUR.items()},
        "clothing": {
            k: v["name"]
            for k, v in gear.ARMOUR.items()
            if k in ("clothes", "thick", "cap", "gloves", "boots", "leggings")
        },
        "ammo": {k: v["name"] for k, v in gear.GEAR["ammo"].items()},
        "remedy": {k: v["name"] for k, v in gear.REMEDIES.items()},
    }


def system_prompt() -> str:
    world = {
        key: content.MATERIALS[key] for key in ("setting", "knowledge_baseline", "material_facts", "flag_meanings")
    }
    return _PROMPT.replace("{world}", json.dumps(world, indent=1)).replace(
        "{gear_classes}", json.dumps(gear_classes(), indent=1)
    )


def judge_craft(context: dict) -> JudgeCall:
    if not config.judge_enabled():
        return JudgeCall(status="disabled", error="No OPENAI_API_KEY in backend/.env, or AI_MODE=off.")
    if config.mode() == "stub":
        return _stub_judgement(context)
    model, reasoning = config.judge_model(), config.judge_reasoning()
    call = JudgeCall(status="error", model=model, reasoning=reasoning)
    messages = [
        {"role": "developer", "content": system_prompt()},
        {"role": "user", "content": json.dumps(context, indent=1)},
    ]
    started = time.perf_counter()
    for attempt in range(2):
        call.attempts = attempt + 1
        try:
            response = config.client().responses.parse(
                model=model, input=messages, text_format=JudgeResult, reasoning={"effort": reasoning}, store=False
            )
        except Exception as error:  # Provider/API errors are reported, never guessed around.
            call.error = f"{type(error).__name__}: {error}"
            call.attempt_errors.append(call.error)
            if not _worth_retry(error):
                break
            continue
        usage = response.usage
        if usage is not None:
            call.input_tokens += usage.input_tokens
            call.output_tokens += usage.output_tokens
        call.raw_output = response.output_text
        parsed = response.output_parsed
        if parsed is not None:
            call.status, call.result, call.error = "ok", parsed.model_dump(), None
            break
        call.error = "The model returned no parsable result (possibly a refusal)."
        call.attempt_errors.append(call.error)
        messages.append(
            {
                "role": "developer",
                "content": "Your previous reply did not match the required schema. Reply again with only the schema.",
            }
        )
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call


def _stub_judgement(context: dict) -> JudgeCall:
    """AI_MODE=stub: a deterministic answer for testing the pipeline without a model.

    Bundles the highlighted portable items (or the first one) into a new object.
    """
    items = [i for i in context["available_items"] if i["portable"]]
    chosen = [i for i in items if i["id"] in context["highlighted_ids"]] or items[:1]
    empty = {
        "take_ids": [],
        "transformation": None,
        "harm": None,
        "fill": None,
        "change": None,
        "demonstration": None,
        "give": None,
        "install": None,
        "lift_out": None,
        "offer_trade": None,
        "gather": None,
        "treat": None,
        "equip": None,
    }
    if not chosen:
        step = Step(
            action="make",
            outcome="blocked",
            reason="You have nothing to work with.",
            effort_seconds=0,
            new_object=None,
            **empty,
        )
    else:
        step = Step(
            action="make",
            outcome="success",
            reason="(Stub judge) You bind the pieces into one bundle.",
            effort_seconds=10,
            **empty,
            new_object=NewObject(
                name="stub bundle",
                description="A test bundle of " + ", ".join(i["name"] for i in chosen) + ".",
                materials=sorted({m for i in chosen for m in i["materials"]}),
                consumes=[i["id"] for i in chosen],
                tools_used=[],
                mass_kg=sum(i["mass_kg"] for i in chosen),
                length_m=None,
                capacity_l=None,
                rated_load_kg=None,
                flags=[],
                capabilities=[Capability(text="exists for testing", status="expected")],
                gear=None,
            ),
        )
    result = JudgeResult(clarifying_question=None, precedent_key="stub:bundle", steps=[step])
    return JudgeCall(
        status="ok", result=result.model_dump(), model="stub", raw_output=result.model_dump_json(), attempts=1
    )


def _worth_retry(error: Exception) -> bool:
    from openai import APIConnectionError, APITimeoutError, InternalServerError
    from pydantic import ValidationError

    return isinstance(error, (APIConnectionError, APITimeoutError, InternalServerError, ValidationError))
