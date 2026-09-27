"""Decider role: typed NPC decisions (choice / score / yes-no) about a described situation.

Jev (TypeSafe System One) is the default: it returns probabilities for predefined options
and is reached either directly at TypeSafe or through the defapi.org gateway (keys starting "dk-"),
and never writes prose or invents actions. If Jev is unavailable, the same questions go to
the LLM decider (MODEL_DECIDER) with a strict schema, and answers come back in Jev's shape.
Gameplay code only ever sees Jev-shaped answers.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import httpx

from . import config

JEV_ROUTES = {  # provider -> (endpoint, default model). Both take the same request and return the same answers.
    "defapi": ("https://api.defapi.org/api/v1/decisions", "typesafe/jev-1.13"),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "jev-latest"),
}
_jev_disabled_reason: str | None = None  # Set after an authentication failure, so we stop retrying.
_lock = threading.Lock()


def jev_key() -> str:
    return os.environ.get("TYPESAFE_API_KEY", "").strip()


def jev_route() -> tuple[str, str, str]:
    """(provider, endpoint, model). JEV_PROVIDER overrides detection from the key's prefix."""
    provider = os.environ.get("JEV_PROVIDER", "").strip().lower() or (
        "defapi" if jev_key().startswith("dk-") else "typesafe")
    url, model = JEV_ROUTES.get(provider, JEV_ROUTES["typesafe"])
    return provider, url, os.environ.get("JEV_MODEL", "").strip() or model


def mode() -> str:
    """'jev', 'llm' or 'off' for this process right now."""
    preferred = os.environ.get("DECIDER", "jev").strip().lower() or "jev"
    if config.mode() == "stub":
        return "stub"
    if preferred == "jev" and jev_key() and _jev_disabled_reason is None:
        return "jev"
    return "llm" if config.judge_enabled() else "off"


def status() -> dict:
    return {"decider": mode(), "jev_key": bool(jev_key()), "jev_error": _jev_disabled_reason,
            "jev_provider": jev_route()[0] if jev_key() else None, "jev_model": jev_route()[2] if jev_key() else None,
            "decider_model": os.environ.get("MODEL_DECIDER", "gpt-6-luna")}


@dataclass
class DeciderCall:
    provider: str
    model: str | None = None
    answers: dict = field(default_factory=dict)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # Reported by the gateway when available.
    error: str | None = None
    fallback_from: str | None = None  # e.g. "jev: 401 authentication_error"

    @property
    def ok(self) -> bool:
        return bool(self.answers) and self.error is None

    def as_dict(self) -> dict:
        return asdict(self)


def decide(state_text: str, questions: dict) -> DeciderCall:
    """Ask all questions about one situation in a single request."""
    current = mode()
    if current == "stub":
        return _stub(questions)
    if current == "off":
        return DeciderCall(provider="off", error="No TypeSafe or OpenAI key configured.")
    if current == "jev":
        call = _jev(state_text, questions)
        if call.ok:
            return call
        fallback = f"jev: {call.error}"
        call = _llm(state_text, questions)
        call.fallback_from = fallback
        return call
    return _llm(state_text, questions)


def decide_many(requests: list[tuple[str, dict]]) -> list[DeciderCall]:
    if not requests:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(requests))) as pool:
        return list(pool.map(lambda request: decide(*request), requests))


def _jev(state_text: str, questions: dict) -> DeciderCall:
    global _jev_disabled_reason
    provider, url, model = jev_route()
    call = DeciderCall(provider=f"jev/{provider}", model=model)
    started = time.perf_counter()
    try:
        response = httpx.post(url, json={"state": state_text, "model": model, "questions": questions},
                              headers={"Authorization": f"Bearer {jev_key()}"}, timeout=20.0)
    except httpx.HTTPError as error:
        call.error = f"{type(error).__name__}: {error}"
    else:
        call.latency_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code in (401, 403):
            with _lock:
                _jev_disabled_reason = f"{response.status_code}: {response.text[:200]}"
            call.error = f"{response.status_code} authentication_error"
        elif response.status_code != 200:
            call.error = f"HTTP {response.status_code}: {response.text[:200]}"
        else:
            data = response.json()
            call.model = data.get("model", call.model)
            call.answers = data.get("answers", {})
            usage = data.get("usage") or {}
            call.input_tokens, call.output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            consumed = data.get("consumed", usage.get("cost"))
            call.cost_usd = float(consumed) if consumed is not None else None
            missing = [name for name in questions if name not in call.answers]
            if missing:
                call.error = f"missing answers: {missing}"
    call.latency_ms = call.latency_ms or round((time.perf_counter() - started) * 1000)
    return call


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
    model = os.environ.get("MODEL_DECIDER", "gpt-6-luna").strip() or "gpt-6-luna"
    call = DeciderCall(provider="llm", model=model)
    prompt = ("You decide what a character in a grounded premodern RPG does, as a game's typed decision engine. "
              "Answer every question strictly from the situation and the character's personality, knowledge and "
              "feelings. For choices pick exactly one listed option; for scales pick the level index (0 = first "
              "description); for yes/no give a probability.\n\nQUESTIONS\n" + json.dumps(questions, indent=1))
    started = time.perf_counter()
    try:
        response = config.client().responses.create(
            model=model, reasoning={"effort": "low"}, store=False,
            input=[{"role": "developer", "content": prompt}, {"role": "user", "content": state_text}],
            text={"format": {"type": "json_schema", "name": "decision", "schema": _schema(questions),
                             "strict": True}})
        raw = json.loads(response.output_text)
    except Exception as error:
        call.error = f"{type(error).__name__}: {error}"
        call.latency_ms = round((time.perf_counter() - started) * 1000)
        return call
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    if response.usage is not None:
        call.input_tokens, call.output_tokens = response.usage.input_tokens, response.usage.output_tokens
    for name, question in questions.items():  # Reshape into Jev's answer format.
        value = raw[name]
        if question["type"] == "choice":
            call.answers[name] = {"type": "choice", "choice": value, "confidence": 1.0,
                                  "probabilities": {key: float(key == value) for key in question["criteria"]}}
        elif question["type"] == "score":
            call.answers[name] = {"type": "score", "score": float(value), "confidence": 1.0,
                                  "probabilities": {str(i): float(i == value) for i in range(len(question["criteria"]))}}
        else:
            call.answers[name] = {"type": "noul", "noul": max(0.0, min(1.0, float(value)))}
    return call


def _stub(questions: dict) -> DeciderCall:
    """AI_MODE=stub: deterministic answers (the first option, the lowest level, yes)."""
    answers = {}
    for name, question in questions.items():
        if question["type"] == "choice":
            first = next(iter(question["criteria"]))
            answers[name] = {"type": "choice", "choice": first, "confidence": 1.0,
                             "probabilities": {key: float(key == first) for key in question["criteria"]}}
        elif question["type"] == "score":
            answers[name] = {"type": "score", "score": 0.0, "confidence": 1.0, "probabilities": {"0": 1.0}}
        else:
            answers[name] = {"type": "noul", "noul": 1.0}
    return DeciderCall(provider="stub", model="stub", answers=answers)
