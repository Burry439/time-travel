"""Decider role: typed NPC decisions (choice / score / yes-no) about a described situation.

Code builds the legal options and asks typed questions; the language model (MODEL_DECIDER, default
gpt-6-luna) answers them against a strict JSON schema, so it never writes prose or invents actions,
and code applies the answer ("models propose; the reducer decides"). The same model voices the
characters, so one mind stands behind what a person decides and what they say (D-46, D-47).

Answers keep one shape for all callers: choices with their probabilities, scores, and yes/no as a
probability ("noul"). The interface is kept deliberately narrow so another typed engine could serve
it again later (for example crowds inside the city), behind the same questions.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from . import config


def model() -> str:
    return os.environ.get("MODEL_DECIDER", "gpt-6-luna").strip() or "gpt-6-luna"


def reasoning() -> str:
    return os.environ.get("DECIDER_REASONING", "low").strip() or "low"


def mode() -> str:
    """'llm', 'stub' or 'off' for this process right now."""
    if config.mode() == "stub":
        return "stub"
    return "llm" if config.judge_enabled() else "off"


def status() -> dict:
    return {"decider": mode(), "decider_model": model(), "decider_reasoning": reasoning()}


@dataclass
class DeciderCall:
    provider: str
    model: str | None = None
    answers: dict = field(default_factory=dict)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    error: str | None = None
    fallback_from: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.answers) and self.error is None

    def as_dict(self) -> dict:
        return asdict(self)


def decide(state_text: str, questions: dict) -> DeciderCall:
    """Ask all questions about one situation in a single request. Never raises: a failure is call.error."""
    try:
        current = mode()
        if current == "stub":
            return _stub(questions)
        if current == "off":
            return DeciderCall(provider="off", error="No OpenAI key configured.")
        return _llm(state_text, questions)
    except Exception as error:  # A decision that can't be made must never take a request down with it.
        return DeciderCall(provider="error", error=f"{type(error).__name__}: {error}")


def decide_many(requests: list[tuple[str, dict]]) -> list[DeciderCall]:
    if not requests:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(requests))) as pool:
        return list(pool.map(lambda request: decide(*request), requests))


def _schema(questions: dict) -> dict:
    properties = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            properties[name] = {"type": "string", "enum": list(question["criteria"])}
        elif question["type"] == "score":
            properties[name] = {"type": "integer", "enum": list(range(len(question["criteria"])))}
        else:
            properties[name] = {"type": "number", "description": "probability from 0 to 1 that the answer is yes"}
    return {"type": "object", "properties": properties, "required": list(questions), "additionalProperties": False}


def _llm(state_text: str, questions: dict) -> DeciderCall:
    call = DeciderCall(provider="llm", model=model())
    prompt = (
        "You decide what a character in a grounded premodern RPG does, as a game's typed decision engine. "
        "Answer every question strictly from the situation and the character's personality, knowledge and "
        "feelings. For choices pick exactly one listed option; for scales pick the level index (0 = first "
        "description); for yes/no give a probability.\n\nQUESTIONS\n" + json.dumps(questions, indent=1)
    )
    started = time.perf_counter()
    raw, response = None, None
    for _attempt in range(2):  # One retry when the output isn't valid JSON (rare, but it happens).
        try:
            response = config.client().responses.create(
                model=call.model,
                reasoning={"effort": reasoning()},
                store=False,
                input=[{"role": "developer", "content": prompt}, {"role": "user", "content": state_text}],
                text={
                    "format": {"type": "json_schema", "name": "decision", "schema": _schema(questions), "strict": True}
                },
            )
            raw = json.loads(response.output_text)
            call.error = None
            break
        except json.JSONDecodeError as error:  # Malformed output: ask once more.
            call.error = f"{type(error).__name__}: {error}"
        except Exception as error:  # Network, TLS, the service: give up; the caller falls back.
            call.error = f"{type(error).__name__}: {error}"
            break
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    if raw is None:
        return call
    if response.usage is not None:
        call.input_tokens, call.output_tokens = response.usage.input_tokens, response.usage.output_tokens
    missing = [name for name in questions if name not in raw]
    if missing:
        call.error = f"missing answers: {missing}"
        return call
    for name, question in questions.items():
        value = raw[name]
        if question["type"] == "choice":
            call.answers[name] = {
                "type": "choice",
                "choice": value,
                "confidence": 1.0,
                "probabilities": {key: float(key == value) for key in question["criteria"]},
            }
        elif question["type"] == "score":
            call.answers[name] = {
                "type": "score",
                "score": float(value),
                "confidence": 1.0,
                "probabilities": {str(i): float(i == value) for i in range(len(question["criteria"]))},
            }
        else:
            call.answers[name] = {"type": "noul", "noul": max(0.0, min(1.0, float(value)))}
    return call


def _stub(questions: dict) -> DeciderCall:
    """AI_MODE=stub: deterministic answers (the first option, the lowest level, yes)."""
    answers = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            first = next(iter(question["criteria"]))
            answers[name] = {
                "type": "choice",
                "choice": first,
                "confidence": 1.0,
                "probabilities": {key: float(key == first) for key in question["criteria"]},
            }
        elif question["type"] == "score":
            answers[name] = {"type": "score", "score": 0.0, "confidence": 1.0, "probabilities": {"0": 1.0}}
        else:
            answers[name] = {"type": "noul", "noul": 1.0}
    return DeciderCall(provider="stub", model="stub", answers=answers)
