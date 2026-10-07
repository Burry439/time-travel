"""Decider role: typed NPC decisions (choice / score / yes-no) about a described situation.

Code builds the legal options and asks typed questions; the language model (MODEL_DECIDER, default
gpt-6-luna) answers them, so it never writes prose or invents actions, and code applies the answer
("models propose; the reducer decides"). The same model voices the characters, so one mind stands
behind what a person decides and what they say (D-46, D-47).

Two ways to ask (DECIDER_BACKEND, D-71): OpenAI's Decisions API, which answers typed questions directly
and about ten times faster, or a Responses call against a strict JSON schema. A Decisions call that fails
or refuses is asked once more the Responses way, inside what's left of the request's budget.

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


def backend() -> str:
    """'decisions' (OpenAI's Decisions API, D-71) or 'responses' (a strict JSON schema, D-47)."""
    chosen = os.environ.get("DECIDER_BACKEND", "decisions").strip().lower()
    return chosen if chosen in ("decisions", "responses") else "decisions"


# A Decisions call answers in under a second; past this it is stuck (the beta has answered 504s after a long wait),
# and the rest of the budget goes to asking the Responses way instead.
DECISIONS_TIMEOUT_S = 3.0


def mode() -> str:
    """'llm', 'stub' or 'off' for this process right now."""
    if config.mode() == "stub":
        return "stub"
    return "llm" if config.judge_enabled() else "off"


def status() -> dict:
    return {"decider": mode(), "decider_backend": backend(), "decider_model": model(), "decider_reasoning": reasoning()}


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


def decide(state_text: str, questions: dict, brief: str = "") -> DeciderCall:
    """Ask all questions about one situation in a single request. Never raises: a failure is call.error. `brief` says
    what kind of judgement this is when it isn't a character deciding (D-71: sorting a typed line)."""
    brief = brief or BRIEF
    try:
        current = mode()
        if current == "stub":
            return _stub(questions)
        if current == "off":
            return DeciderCall(provider="off", error="No OpenAI key configured.")
        if backend() == "responses":
            return _llm(state_text, questions, brief)
        asked = _decisions(state_text, questions, brief)
        if asked.ok:
            return asked
        call = _llm(state_text, questions, brief)  # Once more, the Responses way, in what's left of the budget.
        call.fallback_from = f"decisions: {asked.error}"
        call.latency_ms += asked.latency_ms
        call.input_tokens += asked.input_tokens
        return call
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


BRIEF = (
    "You decide what a character in a grounded premodern RPG does, as a game's typed decision engine. "
    "Answer every question strictly from the situation and the character's personality, knowledge and feelings."
)


def _options(criteria) -> list[tuple[str, str]]:
    """(key, description) for each option or level, whether the question lists them or maps keys to descriptions."""
    if isinstance(criteria, dict):
        return [(str(key), str(text)) for key, text in criteria.items()]
    return [(str(text), str(text)) for text in criteria]


def _question(name: str, question: dict) -> dict:
    """One of our typed questions as the Decisions API asks it: choice, score (ordered levels) or predicate."""
    instructions = str(question.get("instructions") or name)
    if question["type"] == "choice":
        choices = [{"value": key, "description": text} for key, text in _options(question["criteria"])]
        return {"type": "choice", "name": name, "instructions": instructions, "choices": choices}
    if question["type"] == "score":
        levels = [{"label": str(i), "description": text} for i, (_, text) in enumerate(_options(question["criteria"]))]
        return {"type": "score", "name": name, "instructions": instructions, "levels": levels}
    return {"type": "predicate", "name": name, "instructions": instructions}


def _answer(question: dict, answer) -> dict | None:
    """The API's answer in the shape callers read. None for a refusal or an answer that doesn't fit the question."""
    kind = getattr(answer, "type", None)
    if question["type"] == "choice" and kind == "choice":
        keys = [key for key, _ in _options(question["criteria"])]
        if answer.choice not in keys:
            return None
        chances = {key: 0.0 for key in keys}
        chances.update({str(p.value): float(p.probability) for p in answer.probabilities if str(p.value) in chances})
        return {
            "type": "choice",
            "choice": answer.choice,
            "confidence": float(answer.confidence),
            "probabilities": chances,
        }
    if question["type"] == "score" and kind == "score":
        top = len(question["criteria"]) - 1
        chances = {str(p.value): float(p.probability) for p in answer.probabilities if 0 <= p.value <= top}
        total = sum(chances.values())
        # The level the probabilities point to, as an index from 0. The returned score is not used: the API's own
        # documentation shows one (1.1) that its levels' probabilities don't give.
        score = sum(int(level) * p for level, p in chances.items()) / total if total > 0 else float(answer.score)
        return {
            "type": "score",
            "score": max(0.0, min(float(top), score)),
            "confidence": float(answer.confidence),
            "probabilities": chances,
        }
    if question["type"] not in ("choice", "score") and kind == "predicate":
        return {"type": "noul", "noul": max(0.0, min(1.0, float(answer.probability)))}
    return None


def _decisions(state_text: str, questions: dict, brief: str = BRIEF) -> DeciderCall:
    """All the questions in one Decisions API request (D-71). Fails (call.error) rather than guess."""
    call = DeciderCall(provider="decisions", model=model())
    started = time.perf_counter()
    try:
        response = config.client(DECISIONS_TIMEOUT_S).decisions.create(
            model=call.model,
            input=f"{brief}\n\nSITUATION\n{state_text}",
            questions=[_question(name, question) for name, question in questions.items()],
        )
    except Exception as error:  # Network, the service, the beta: the caller asks the Responses way instead.
        call.error = f"{type(error).__name__}: {error}"
        call.latency_ms = round((time.perf_counter() - started) * 1000)
        return call
    call.latency_ms = round((time.perf_counter() - started) * 1000)
    if getattr(response, "usage", None) is not None:
        call.input_tokens = int(response.usage.input_tokens)
        call.output_tokens = int(response.usage.output_tokens)
    given = {answer.name: answer for answer in response.answers}
    for name, question in questions.items():
        shaped = _answer(question, given[name]) if name in given else None
        if shaped is None:
            refused = name in given and getattr(given[name], "type", None) == "refusal"
            call.error = f"{'refused' if refused else 'no usable answer to'} {name}"
            call.answers = {}
            return call
        call.answers[name] = shaped
    return call


def _llm(state_text: str, questions: dict, brief: str = BRIEF) -> DeciderCall:
    call = DeciderCall(provider="llm", model=model())
    prompt = (
        f"{brief} For choices pick exactly one listed option; for scales pick the level index (0 = first "
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
