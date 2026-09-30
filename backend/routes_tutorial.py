"""The tutorial's progress and the device (GDD D-50).

Progress is code: after each change the story is checked (tutorial.tick), and anything that moved on (a step done,
Kade lending his staff, the bout starting) is saved as one `tutorial` event with the resulting fields. The clock
beat checks it too, so nothing depends on the client asking. Asking the device is a `device` event.
"""

from __future__ import annotations

import copy
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import patch
import store
import tutorial
from ai import config as ai_config
from ai import telemetry, voice

router = APIRouter()


class Ask(BaseModel):
    question: str = Field(default="", max_length=400)
    moment: Literal["new_lead", "failure", "angry", "news", "stuck"] | None = None  # It speaks up (D-55).
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
    payload["journal_added"] = probe["journal"][len(state["journal"]) :]
    before = patch.snapshot(state)
    store.apply_tutorial(state, payload)
    store.record(
        connection, before, state, "tutorial", request_id or f"tutorial:{uuid4().hex}", state["sim_time_ms"] // 1000
    )
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


class Read(BaseModel):
    step: int = Field(ge=0)


class UiDone(BaseModel):
    key: str = Field(pattern="^(pack|inspect|journal|book)$")


def _save(connection, state: dict, change, request_id: str) -> bool:
    """Apply a tutorial change to a copy of the world and save it as a `tutorial` event (with the result fields)."""
    probe = copy.deepcopy(state)
    if not change(probe):
        return False
    payload = {key: probe[key] for key in store.TUTORIAL_FIELDS if key in probe}
    payload["journal_added"] = probe["journal"][len(state["journal"]) :]
    before = patch.snapshot(state)
    store.apply_tutorial(state, payload)
    store.record(connection, before, state, "tutorial", request_id, state["sim_time_ms"] // 1000)
    return True


@router.post("/runs/{run_id}/tutorial/read")
def read(run_id: str, request: Read):
    """The player pressed through this step's cards (D-52): its check counts from now, and may already hold."""
    with store.lock, store.db() as connection:
        _, state = store.load_run(connection, run_id)
        if tutorial.active(state) and request.step == state["tutorial"]["step"]:
            _save(connection, state, tutorial.read_cards, f"tutorial-read:{uuid4().hex}")
            progress(connection, state)
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/tutorial/ui")
def ui(run_id: str, request: UiDone):
    """Something the tutorial teaches happened on screen (the pack opened, a closer look, the book read)."""
    with store.lock, store.db() as connection:
        _, state = store.load_run(connection, run_id)
        if tutorial.active(state):
            _save(connection, state, lambda probe: tutorial.ui_done(probe, request.key), f"tutorial-ui:{uuid4().hex}")
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
        payload["journal_added"] = probe["journal"][len(state["journal"]) :]
        before = patch.snapshot(state)
        store.apply_tutorial(state, payload)
        store.record(
            connection, before, state, "tutorial", f"tutorial-skip:{uuid4().hex}", state["sim_time_ms"] // 1000
        )
        progress(connection, state)
    return {"state": state, "duplicate": False}


@router.post("/runs/{run_id}/device/ask")
def ask(run_id: str, request: Ask):
    """H: ask the device anything. It answers from what the stranger knows; its written hint without a model.
    With a moment instead of a question (D-55), it may speak up on its own: at most every two minutes, never over a
    fight or a conversation, and only with a model (no written stand-in for a remark)."""
    question = request.question.strip()
    if not question and not request.moment:
        raise HTTPException(422, "Ask something, or name the moment")
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior_seq = store.check_request(connection, state, request.expected_version, request.request_id)
        if prior_seq is not None:
            return {"state": store.state_at(connection, run, prior_seq), "duplicate": True}
        moment = None if question else request.moment
        if moment and (not tutorial.moment_allowed(state) or tutorial.moment_detail(state, moment) is None):
            return {"state": state, "duplicate": False, "skipped": True}
        context = tutorial.device_context(state, question, moment)
        fallback = "" if moment else tutorial.fallback_answer(state)
        allowed = telemetry.calls_for_run(connection, run_id) < ai_config.max_calls_per_run()
    call = voice.device(context, fallback, allowed)  # Outside the lock.
    if moment and call.status != "ok":
        return {"state": state, "duplicate": False, "skipped": True}
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if call.model and call.model != "stub":
            telemetry.record(
                connection,
                run_id,
                "voice",
                call.model,
                call.prompt_version,
                call.latency_ms,
                call.status == "ok",
                call.error,
                call.input_tokens,
                call.output_tokens,
            )
        probe = copy.deepcopy(state)
        tutorial.device_says(probe, call.text, "remark" if moment else "answer", question or None)
        payload = {"device_log": probe["device_log"], "journal_added": probe["journal"][len(state["journal"]) :]}
        before = patch.snapshot(state)
        store.apply_tutorial(state, payload)
        store.record(connection, before, state, "device", request.request_id, state["sim_time_ms"] // 1000)
    reply = {"state": state, "duplicate": False, "answer": call.text, "status": call.status}
    if run["mode"] == "developer":
        reply["trace"] = {"context": context, "voice": call.as_dict()}
    return reply
