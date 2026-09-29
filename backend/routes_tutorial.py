"""The tutorial's progress and the device (GDD D-50).

Progress is code: after each change the story is checked (tutorial.tick), and anything that moved on (a step done,
Kade lending his staff, the bout starting) is saved as one `tutorial` event with the resulting fields. The clock
beat checks it too, so nothing depends on the client asking. Asking the device is a `device` event.
"""
from __future__ import annotations

import copy
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import store
import tutorial
from ai import config as ai_config, telemetry, voice

router = APIRouter()


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=400)
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def progress(connection, state: dict, request_id: str | None = None) -> bool:
    """Check the story and save whatever moved on as a `tutorial` event. The caller holds the lock."""
    if not tutorial.active(state):
        return False
    probe = copy.deepcopy(state)
    if not tutorial.tick(probe):
        return False
    payload = {key: probe[key] for key in store.TUTORIAL_FIELDS if key in probe}
    payload["journal_added"] = probe["journal"][len(state["journal"]):]
    store.append(connection, state, "tutorial", payload, request_id or f"tutorial:{uuid4().hex}",
                 state["sim_time_ms"] // 1000)
    store.apply_tutorial(state, payload)
    return True


def after_action(state: dict) -> None:
    """Right after the stranger does something (not only on the next clock beat, which a panel may pause)."""
    if tutorial.active(state):
        with store.lock, store.db() as connection:
            _, latest = store.load_run(connection, state["run_id"])
            if progress(connection, latest):
                state.clear()
                state.update(latest)


@router.post("/runs/{run_id}/tutorial/check")
def check(run_id: str):
    with store.lock, store.db() as connection:
        _, state = store.load_run(connection, run_id)
        progress(connection, state)
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/tutorial/skip")
def skip(run_id: str):
    """Developer only: complete the current step (for testing each step)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if run["mode"] != "developer":
            raise HTTPException(403, "Developer control is unavailable in normal mode")
        if not tutorial.active(state):
            return {"state": state, "duplicate": False}
        probe = copy.deepcopy(state)
        tutorial.skip(probe)
        payload = {key: probe[key] for key in store.TUTORIAL_FIELDS if key in probe}
        payload["journal_added"] = probe["journal"][len(state["journal"]):]
        store.append(connection, state, "tutorial", payload, f"tutorial-skip:{uuid4().hex}",
                     state["sim_time_ms"] // 1000)
        store.apply_tutorial(state, payload)
        progress(connection, state)
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/device/ask")
def ask(run_id: str, request: Ask):
    """H: ask the device anything. It answers from what the stranger knows; its written hint without a model."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        context = tutorial.device_context(state, request.question.strip())
        fallback = tutorial.fallback_answer(state)
        allowed = telemetry.calls_for_run(connection, run_id) < ai_config.max_calls_per_run()
    call = voice.device(context, fallback, allowed)  # Outside the lock.
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if call.model and call.model != "stub":
            telemetry.record(connection, run_id, "voice", call.model, call.prompt_version, call.latency_ms,
                             call.status == "ok", call.error, call.input_tokens, call.output_tokens)
        probe = copy.deepcopy(state)
        tutorial.device_says(probe, call.text, "answer", request.question.strip())
        payload = {"device_log": probe["device_log"], "journal_added": probe["journal"][len(state["journal"]):]}
        store.append(connection, state, "device", payload, request.request_id, state["sim_time_ms"] // 1000)
        store.apply_tutorial(state, payload)
    reply = {"state": state, "duplicate": False, "answer": call.text, "status": call.status}
    if run["mode"] == "developer":
        reply["trace"] = {"context": context, "voice": call.as_dict()}
    return reply
