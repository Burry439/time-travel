"""Physics judge role: turns a crafting intention plus world context into a proposal.

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

from . import config

PROMPT_VERSION = "judge_v1"
_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
_WORLD = json.loads((Path(__file__).resolve().parents[2] / "data" / "content" / "materials.json").read_text(encoding="utf-8"))

Flag = Literal[
    "rigid", "flexible", "sharp_edge", "tieable", "adhesive", "container", "watertight", "floats",
    "combustible", "ferromagnetic", "magnetized", "magnet_source", "light_source", "heat_source",
    "sound_loud", "reflective", "indicates_direction", "measures_length", "stable_support", "fulcrum",
]


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


class JudgeResult(BaseModel):
    outcome: Literal["success", "failed", "blocked", "needs_clarification", "unsupported"]
    reason: str
    effort_seconds: int
    clarifying_question: str | None
    precedent_key: str
    new_object: NewObject | None


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


def system_prompt() -> str:
    world = {key: _WORLD[key] for key in ("setting", "knowledge_baseline", "material_facts", "flag_meanings")}
    return _PROMPT.replace("{world}", json.dumps(world, indent=1))


def judge_craft(context: dict) -> JudgeCall:
    if not config.judge_enabled():
        return JudgeCall(status="disabled", error="No OPENAI_API_KEY in backend/.env, or AI_MODE=off.")
    if config.mode() == "stub":
        return _stub_judgement(context)
    model, reasoning = config.judge_model(), config.judge_reasoning()
    call = JudgeCall(status="error", model=model, reasoning=reasoning)
    messages = [{"role": "developer", "content": system_prompt()},
                {"role": "user", "content": json.dumps(context, indent=1)}]
    started = time.perf_counter()
    for attempt in range(2):
        call.attempts = attempt + 1
        try:
            response = config.client().responses.parse(
                model=model, input=messages, text_format=JudgeResult,
                reasoning={"effort": reasoning}, store=False)
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
        messages.append({"role": "developer",
                         "content": "Your previous reply did not match the required schema. Reply again with only the schema."})
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    return call


def _stub_judgement(context: dict) -> JudgeCall:
    """AI_MODE=stub: a deterministic answer for testing the pipeline without a model.

    Bundles the highlighted items (or the first usable one) into a new object.
    """
    items = [i for i in context["available_items"] if i["consumable"]]
    chosen = [i for i in items if i["id"] in context["highlighted_item_ids"]] or items[:1]
    if not chosen:
        result = JudgeResult(outcome="blocked", reason="You have nothing to work with.", effort_seconds=0,
                             clarifying_question=None, precedent_key="stub:none", new_object=None)
    else:
        result = JudgeResult(
            outcome="success", reason="(Stub judge) You bind the pieces into one bundle.", effort_seconds=10,
            clarifying_question=None, precedent_key="stub:bundle",
            new_object=NewObject(
                name="stub bundle", description="A test bundle of " + ", ".join(i["name"] for i in chosen) + ".",
                materials=sorted({m for i in chosen for m in i["materials"]}), consumes=[i["id"] for i in chosen],
                tools_used=[], mass_kg=sum(i["mass_kg"] for i in chosen), length_m=None, capacity_l=None,
                rated_load_kg=None, flags=[], capabilities=[Capability(text="exists for testing", status="expected")]))
    return JudgeCall(status="ok", result=result.model_dump(), model="stub", raw_output=result.model_dump_json(),
                     attempts=1)


def _worth_retry(error: Exception) -> bool:
    from openai import APIConnectionError, APITimeoutError, InternalServerError
    from pydantic import ValidationError

    return isinstance(error, (APIConnectionError, APITimeoutError, InternalServerError, ValidationError))
