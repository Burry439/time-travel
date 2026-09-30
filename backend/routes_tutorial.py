"""The tutorial's progress and the device (GDD D-50).

Progress is code: after each change the story is checked (tutorial.tick), and anything that moved on (a step done,
Kade lending his gear, the bout starting) is saved as one `tutorial` event. The clock beat checks it too, so nothing
depends on the client asking. Asking the device is a `device` event.
"""

from __future__ import annotations

import copy
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import commands
import device
import scenario
from ai import config as ai_config
from ai import telemetry, voice
from shapes import State

router = APIRouter()

# What a story step may change: taken from the copy it was worked out on (the rest of the world stays as it was).
TUTORIAL_FIELDS = (
    "tutorial",
    "device_log",
    "objective",
    "npcs",
    "objects",
    "player",
    "fight",
    "pending_minds",
    "encounter",
    "admitted",
    "gate_open",
)


class Ask(BaseModel):
    question: str = Field(default="", max_length=400)
    moment: Literal["new_lead", "failure", "angry", "news", "stuck"] | None = None  # It speaks up (D-55).
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


def _moved_on(cmd: commands.Command, change) -> bool:
    """Work a story change out on a copy; if anything moved on, keep it and save it as a `tutorial` event."""
    probe = copy.deepcopy(cmd.state)
    if not change(probe):
        return False
    for key in TUTORIAL_FIELDS:
        if key in probe:
            cmd.state[key] = probe[key]
    cmd.state["journal"].extend(probe["journal"][len(cmd.state["journal"]) :])
    cmd.save("tutorial")
    return True


def progress(cmd: commands.Command) -> bool:
    """Check the story (inside a command that holds the lock) and save whatever moved on."""
    return scenario.active(cmd.state) and _moved_on(cmd, scenario.tick)


def after_action(state: State) -> None:
    """Right after the stranger does something (not only on the next clock beat, which a panel may pause)."""
    if scenario.active(state):
        with commands.open(state["run_id"], playable=False) as cmd:
            if progress(cmd):
                state.clear()
                state.update(cmd.state)


@router.post("/runs/{run_id}/tutorial/check")
def check(run_id: str):
    with commands.open(run_id, playable=False) as cmd:
        progress(cmd)
    return {"state": cmd.state, "duplicate": False}


class Read(BaseModel):
    step: int = Field(ge=0)


class UiDone(BaseModel):
    key: str = Field(pattern="^(pack|inspect|journal|book)$")


@router.post("/runs/{run_id}/tutorial/read")
def read(run_id: str, request: Read):
    """The player pressed through this step's cards (D-52): its check counts from now, and may already hold."""
    with commands.open(run_id, playable=False) as cmd:
        if scenario.active(cmd.state) and request.step == cmd.state["tutorial"]["step"]:
            _moved_on(cmd, scenario.read_cards)
            progress(cmd)
    return {"state": cmd.state, "duplicate": False}


@router.post("/runs/{run_id}/tutorial/ui")
def ui(run_id: str, request: UiDone):
    """Something the tutorial teaches happened on screen (the pack opened, a closer look, the book read)."""
    with commands.open(run_id, playable=False) as cmd:
        if scenario.active(cmd.state):
            _moved_on(cmd, lambda probe: scenario.ui_done(probe, request.key))
            progress(cmd)
    return {"state": cmd.state, "duplicate": False}


@router.post("/runs/{run_id}/tutorial/skip")
def skip(run_id: str):
    """Developer only: complete the current step (for testing each step)."""
    with commands.open(run_id, developer=True, playable=False) as cmd:
        if scenario.active(cmd.state):
            _moved_on(cmd, lambda probe: scenario.skip(probe) or True)
            progress(cmd)
    return {"state": cmd.state, "duplicate": False}


@router.post("/runs/{run_id}/device/ask")
@commands.answers
def ask(run_id: str, request: Ask):
    """H: ask the device anything. It answers from what the stranger knows; its written hint without a model.
    With a moment instead of a question (D-55), it may speak up on its own: at most every two minutes, never over a
    fight or a conversation, and only with a model (no written stand-in for a remark)."""
    question = request.question.strip()
    if not question and not request.moment:
        raise HTTPException(422, "Ask something, or name the moment")
    with commands.open(run_id, request, playable=False) as cmd:
        state = cmd.state
        moment = None if question else request.moment
        if moment and (not device.moment_allowed(state) or device.moment_detail(state, moment) is None):
            return {"state": state, "duplicate": False, "skipped": True}
        context = device.context(state, question, moment)
        fallback = "" if moment else device.fallback_answer(state)
        allowed = telemetry.calls_for_run(cmd.connection, run_id) < ai_config.max_calls_per_run()
    call = voice.device(context, fallback, allowed)  # Outside the lock.
    if moment and call.status != "ok":
        return {"state": state, "duplicate": False, "skipped": True}
    with commands.reopen(run_id, request, stale=False) as cmd:
        if call.model and call.model != "stub":
            telemetry.log(cmd.connection, run_id, "voice", call)
        device.says(cmd.state, call.text, "remark" if moment else "answer", question or None)
        cmd.save("device")
    reply = {"state": cmd.state, "duplicate": False, "answer": call.text, "status": call.status}
    if cmd.developer:
        reply["trace"] = {"context": context, "voice": call.as_dict()}
    return reply
