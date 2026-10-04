"""People thinking: everyone with something on their mind decides, each in a call of their own, in parallel
(D-59: each person is their own agent; one shared request once carried up to six people's briefs side by side).

Reactions to the stranger come first and go alone, so they're never slowed by
the rest. Otherwise people plan their day and talk to each other (D-37),
and anyone whose conversation with the stranger has ended turns it into a memory (D-36) alongside.
Every result is committed by code in one "minds" event, so replay is exact.
"""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import cast
import commands
import minds
import persona
import store
import tuning
import views
import village
from ai import config as ai_config
from ai import decider, telemetry, voice
from shapes import Npc, State

router = APIRouter(route_class=views.Shown)  # Replies carry their state's view (views.py).
KINDS = ("decide", "agenda", "meet", "recollect", "told")
REACTING = ("decide",)
RECOLLECT_BATCH = 3


class ThinkRequest(BaseModel):
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    # Two lanes (D-39): reactions never wait behind people planning their day. "any" = reactions first.
    lane: Literal["any", "react", "village"] = "any"


_thinking_runs: set[tuple[str, str]] = set()


def _meet_ready(state: State, pending: dict) -> bool:
    """Both still free and close enough; otherwise the chat doesn't happen."""
    a, b = cast.find(state["npcs"], pending["npc_id"]), cast.find(state["npcs"], pending["why"])
    return (
        bool(a and b)
        and village.free(state, a)
        and village.free(state, b)
        and cast.distance(a, b) <= tuning.VISIT_REACH + 1
    )


def _choose(state: State, lane: str = "any") -> tuple[list[dict], list[dict], list[dict]]:
    """Who decides now, whose conversations become memories, and stale entries to drop.

    Reactions go alone and never carry memory or chatter work; the village lane takes meetings, agendas
    and memories."""
    alive = [
        p
        for p in state.get("pending_minds", [])
        if p["kind"] in KINDS and (npc := cast.find(state["npcs"], p["npc_id"])) and npc.get("alive", True)
    ]
    reacting = [p for p in alive if p["kind"] in REACTING]
    if lane == "react" or (lane == "any" and reacting):
        return reacting[: tuning.THINK_BATCH], [], []
    stale = [p for p in alive if p["kind"] == "meet" and not _meet_ready(state, p)]  # They went their ways.
    batch = [p for p in alive if p["kind"] == "meet" and _meet_ready(state, p)][: tuning.THINK_BATCH]
    batch += [p for p in alive if p["kind"] == "told"][: tuning.THINK_BATCH]  # Someone was just told something (D-54).
    batch += [p for p in alive if p["kind"] == "agenda"][: tuning.THINK_BATCH - len(batch)]
    talking = set((state.get("encounter") or {}).get("participants") or [])
    recollecting = [p for p in alive if p["kind"] == "recollect" and p["npc_id"] not in talking][:RECOLLECT_BATCH]
    return batch, recollecting, stale


def _recollect_context(npc: Npc) -> tuple[dict, dict]:
    known = persona.knows(npc)
    fold = [e["text"] for e in known["episodes"][: max(0, len(known["episodes"]) - persona.EPISODES_KEPT + 1)]]
    context = {
        "character": {"name": npc["name"], "role": cast.card(npc)["role"]},
        "notes": list(known["notes"]),
        "long_memory": known.get("long_memory", ""),
        "to_fold": fold,
    }
    fallback = {
        "episode": " ".join(known["notes"])[:400],
        "long_memory": " ".join(filter(None, [known.get("long_memory", "")] + fold))[-600:],
    }
    return context, fallback


def _apply_recollection(npc: Npc, context: dict, result: dict, now: int) -> dict:
    """The conversation becomes an episode; the notes it covered are cleared; the oldest episodes fold away."""
    known = persona.knows(npc)
    covered = len(context["notes"])
    known["notes"] = known["notes"][covered:]
    if result["episode"]:
        known["episodes"].append({"at": now, "text": result["episode"]})
    if context["to_fold"]:
        known["episodes"] = known["episodes"][len(context["to_fold"]) :]
        known["long_memory"] = result["long_memory"]
    known["since"] = now
    known["talks"] = known.get("talks", 0) + 1
    return {"npc_id": npc["id"], "kind": "recollect", "episode": result["episode"], "folded": len(context["to_fold"])}


@router.post("/runs/{run_id}/think")
@commands.answers
def think(run_id: str, request: ThinkRequest):
    """Let people with something on their mind decide what to do (model calls run outside the lock)."""
    with commands.open(run_id, request, playable=False, stale=False) as cmd:
        if not cmd.state.get("pending_minds"):
            return {"state": cmd.state, "duplicate": False}
        guard = (run_id, request.lane)
        if (
            guard in _thinking_runs
            or (run_id, "any") in _thinking_runs
            or (request.lane == "any" and any(r == run_id for r, _ in _thinking_runs))
        ):
            raise HTTPException(409, {"reason": "in_progress"})
        plan = _plan(cmd, request.lane)
        _thinking_runs.add(guard)
    records: list[dict] = []
    try:
        heard = _ask(plan)
        with commands.reopen(run_id, request, stale=False) as cmd:
            _log_calls(cmd, heard)
            records = _apply(cmd, plan, heard)
    finally:
        _thinking_runs.discard(guard)
    response = {"state": cmd.state, "duplicate": False}
    if cmd.developer:
        response["decisions"] = records
    return response


def _plan(cmd: commands.Command, lane: str) -> dict:
    """Who thinks now, and what each needs asked: one shared decider request, recollections, chats, hearings.
    Past the decider allowance days go on by routine and chats are small talk; reactions still decide. A chance
    meeting with nothing to pass on is a nod, decided by code (no model call)."""
    over_budget = (
        telemetry.calls_for_run(cmd.connection, cmd.run_id, decider=True) >= ai_config.max_decider_calls_per_run()
    )
    writing_allowed = telemetry.calls_for_run(cmd.connection, cmd.run_id) < ai_config.max_calls_per_run()
    batch, recollecting, stale = _choose(cmd.state, lane)
    snapshot = copy.deepcopy(cmd.state)
    ask = [
        p
        for p in batch
        if p["kind"] != "told"
        and not (over_budget and p["kind"] not in REACTING)
        and not (
            p["kind"] == "meet"
            and not village.has_news(
                snapshot, cast.find(snapshot["npcs"], p["npc_id"]), cast.find(snapshot["npcs"], p["why"])
            )
        )
    ]
    return {
        "batch": batch,
        "recollecting": recollecting,
        "stale": stale,
        "snapshot": snapshot,
        "ask": ask,
        "memory_jobs": [(p, *_recollect_context(cast.find(snapshot["npcs"], p["npc_id"]))) for p in recollecting],
        "writing_allowed": writing_allowed,
    }


def _ask(plan: dict) -> dict:
    """Every model call for this moment, in parallel: the decider (one shared request, then anyone it missed),
    recollections, villagers chatting where the stranger can see them, and people reacting to what they're told."""
    snapshot, ask, writing_allowed = plan["snapshot"], plan["ask"], plan["writing_allowed"]
    calls: dict[str, decider.DeciderCall] = {}
    answers: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        memory_futures = [
            pool.submit(voice.recollect, context, fallback, writing_allowed)
            for _, context, fallback in plan["memory_jobs"]
        ]
        for pending, call in zip(ask, decider.decide_many([decision_request(snapshot, p) for p in ask])):
            calls[pending["npc_id"]] = call
            if call.ok:
                answers[pending["npc_id"]] = call.answers
        chats = {}
        for pending in plan["batch"]:
            a = cast.find(snapshot["npcs"], pending["npc_id"])
            if pending["kind"] != "meet" or not village.chatter_allowed(snapshot, a, snapshot["sim_time_ms"]):
                continue
            b = cast.find(snapshot["npcs"], pending["why"])
            mine = answers.get(a["id"], {})
            topic = village.topics(snapshot, a, b)[village.chosen_topic(snapshot, a, b, mine)]
            chats[a["id"]] = pool.submit(
                voice.chatter,
                village.chatter_context(snapshot, a, b, topic, mine),
                village.fallback_chatter(a, b, topic, mine),
                writing_allowed,
            )
        hearings = {}
        for pending in plan["batch"]:
            if pending["kind"] != "told":
                continue
            listener = cast.find(snapshot["npcs"], pending["npc_id"])
            teller = cast.find(snapshot["npcs"], pending["why"])
            if listener is None or teller is None:
                continue
            message = str(pending.get("message", ""))
            hearings[listener["id"]] = pool.submit(
                voice.hearing,
                village.hearing_context(snapshot, listener, teller, message),
                village.fallback_hearing(listener, teller, message),
                writing_allowed,
            )
        return {
            "calls": calls,
            "answers": answers,
            "remembered": [future.result() for future in memory_futures],
            "heard_back": {npc_id: future.result() for npc_id, future in hearings.items()},
            "spoken": {npc_id: future.result() for npc_id, future in chats.items()},
        }


def _log_calls(cmd: commands.Command, heard: dict) -> None:
    for call in heard["calls"].values():
        telemetry.log(cmd.connection, cmd.run_id, "decider", call)
    for call, _ in heard["remembered"] + list(heard["spoken"].values()) + list(heard["heard_back"].values()):
        if call.model and call.model != "stub" and call.status in ("ok", "fallback") and call.latency_ms:
            role = "memory" if call.prompt_version.startswith("recollect") else "chatter"
            telemetry.log(cmd.connection, cmd.run_id, role, call)


def _apply(cmd: commands.Command, plan: dict, heard: dict) -> list[dict]:
    """What everyone decided, on the latest world (worked out on a copy, then saved as one `minds` event)."""
    state, connection = cmd.state, cmd.connection
    batch, snapshot = plan["batch"], plan["snapshot"]
    calls, answers, spoken, heard_back = heard["calls"], heard["answers"], heard["spoken"], heard["heard_back"]
    records: list[dict] = []
    working = copy.deepcopy(state)
    handled = {(p["npc_id"], p["kind"]) for p in batch + plan["recollecting"] + plan["stale"]}
    working["pending_minds"] = [
        p
        for p in working.get("pending_minds", [])
        if p["kind"] in KINDS
        and (p["npc_id"], p["kind"]) not in handled
        and (n := cast.find(working["npcs"], p["npc_id"]))
        and n.get("alive", True)
        and not n.get("down")
    ]
    now, journal, learned = working["sim_time_ms"], [], []
    for pending in batch:
        npc = cast.find(working["npcs"], pending["npc_id"])
        call = calls.get(pending["npc_id"])
        record = {
            "npc_id": pending["npc_id"],
            "kind": pending["kind"],
            "why": pending["why"],
            "skipped": None,
        }
        mine = answers.get(pending["npc_id"])
        if npc is None or not npc.get("alive", True):
            record["skipped"] = "no longer alive"
        elif pending["kind"] == "agenda":
            if village.free(working, npc):
                record.update(village.apply_agenda(working, npc, mine or {}, now))  # No answer: carry on.
            else:
                record["skipped"] = "busy with something else now"
        elif pending["kind"] == "told":
            teller = cast.find(working["npcs"], pending["why"])
            call_result = heard_back.get(npc["id"])
            if teller is None or call_result is None:
                record["skipped"] = "the teller is gone"
            else:
                record.update(
                    village.apply_hearing(
                        working, npc, teller, str(pending.get("message", "")), call_result[1], now, journal
                    )
                )
                record["voice"] = call_result[0].as_dict()
        elif pending["kind"] == "meet":
            if _meet_ready(working, pending):
                other = cast.find(working["npcs"], pending["why"])
                said = spoken.get(npc["id"])
                record.update(village.apply_meeting(working, npc, other, mine or {}, said[1] if said else None, now))
                learned += record.pop("learned")
            else:
                record["skipped"] = "they went their separate ways"
        elif mine is None:
            record["skipped"] = f"decider failed: {call.error if call else 'no answer'}"
        else:
            record.update(minds.apply_decision(working, npc, mine, now, journal))
        records.append(record)
        if pending["kind"] == "told":  # A voice call, not the decider: its context is in record["voice"].
            situation, questions = str(pending.get("message", "")), {}
        else:
            situation, questions = decision_request(snapshot, pending)
        trace = {
            **record,
            "situation": situation,
            "questions": questions,
            "call": call.as_dict() if call else {},
            "people_in_request": 1,
        }
        if pending["kind"] == "meet" and spoken.get(pending["npc_id"]):
            trace["chatter"] = spoken[pending["npc_id"]][0].as_dict()
        _trace(connection, cmd.run_id, state["event_seq"] + 1, pending["npc_id"], trace)
    for (pending, context, _), (call, result) in zip(plan["memory_jobs"], heard["remembered"]):
        npc = cast.find(working["npcs"], pending["npc_id"])
        if npc is None:
            continue
        record = _apply_recollection(npc, context, result, now)
        records.append(record)
        trace = {**record, "why": "the conversation ended", "notes": context["notes"], "voice": call.as_dict()}
        _trace(connection, cmd.run_id, state["event_seq"] + 1, npc["id"], trace)
    people = {
        "npcs": working["npcs"],
        "player": working["player"],
        "pending_minds": working.get("pending_minds", []),
        "people_journal": journal,
        "encounter": working.get("encounter"),
        "fight": working.get("fight"),
        "learned_added": learned,
        "village": working.get("village", state.get("village", {"chatter_at": []})),
    }
    state["npcs"], state["player"] = people["npcs"], people["player"]
    store.apply_people(state, people)
    cmd.save("minds", state["tick"])
    return records


def _trace(connection, run_id: str, event_seq: int, npc_id: str, trace: dict) -> None:
    connection.execute(
        "INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
        (run_id, event_seq, npc_id, json.dumps(trace)),
    )


ANSWER_KEY = {"decide": "action", "agenda": "agenda", "meet": "topic"}  # Must be answered.


def _brief(state: State, npc: Npc, pending: dict, prefix: str = "") -> tuple[str, dict]:
    """A person's situation and questions: reacting to what they saw, what to do next with their day, or what to
    talk about with someone they've met (D-37)."""
    if pending["kind"] in ("agenda", "meet"):
        if pending["kind"] == "agenda":
            return village.agenda_brief(state, npc, prefix)
        return village.meet_brief(state, npc, cast.find(state["npcs"], pending["why"]), prefix)
    return minds.situation(state, npc), minds.questions(state, npc, prefix)


def decision_request(state: State, pending: dict) -> tuple[str, dict]:
    """One person's own request: only their brief, never anyone else's (D-59: each person is their own agent)."""
    return _brief(state, cast.find(state["npcs"], pending["npc_id"]), pending)
