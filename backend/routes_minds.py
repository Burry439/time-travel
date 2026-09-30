"""People thinking: everyone with something on their mind decides, in one decider request.

Reactions to the stranger come first and go alone, so they're never slowed by
the rest. Otherwise people plan their day and talk to each other (D-37) in the same shared request,
and anyone whose conversation with the stranger has ended turns it into a memory (D-36) alongside.
Every result is committed by code in one "minds" event, so replay is exact.
"""
from __future__ import annotations

import copy
import json
import math
from concurrent.futures import ThreadPoolExecutor

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import minds
import persona
import store
import village
from ai import config as ai_config
from ai import decider, telemetry, voice

router = APIRouter()
KINDS = ("decide", "agenda", "meet", "recollect", "told")
REACTING = ("decide",)
RECOLLECT_BATCH = 3


class ThinkRequest(BaseModel):
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    # Two lanes (D-39): reactions never wait behind people planning their day. "any" = reactions first.
    lane: Literal["any", "react", "village"] = "any"


_thinking_runs: set[tuple[str, str]] = set()


def _meet_ready(state: dict, pending: dict) -> bool:
    """Both still free and close enough; otherwise the chat doesn't happen."""
    a, b = minds.find(state["npcs"], pending["npc_id"]), minds.find(state["npcs"], pending["why"])
    return bool(a and b) and village.free(state, a) and village.free(state, b) \
        and math.dist(minds._cell(a), minds._cell(b)) <= village.VISIT_REACH + 1


def _choose(state: dict, lane: str = "any") -> tuple[list[dict], list[dict], list[dict]]:
    """Who decides now, whose conversations become memories, and stale entries to drop.

    Reactions go alone and never carry memory or chatter work; the village lane takes meetings, agendas
    and memories."""
    alive = [p for p in state.get("pending_minds", []) if p["kind"] in KINDS
             and (npc := minds.find(state["npcs"], p["npc_id"])) and npc.get("alive", True)]
    reacting = [p for p in alive if p["kind"] in REACTING]
    if lane == "react" or (lane == "any" and reacting):
        return reacting[:minds.THINK_BATCH], [], []
    stale = [p for p in alive if p["kind"] == "meet" and not _meet_ready(state, p)]  # They went their ways.
    batch = [p for p in alive if p["kind"] == "meet" and _meet_ready(state, p)][:minds.THINK_BATCH]
    batch += [p for p in alive if p["kind"] == "told"][:minds.THINK_BATCH]  # Someone was just told something (D-54).
    batch += [p for p in alive if p["kind"] == "agenda"][:minds.THINK_BATCH - len(batch)]
    talking = set((state.get("encounter") or {}).get("participants") or [])
    recollecting = [p for p in alive if p["kind"] == "recollect" and p["npc_id"] not in talking][:RECOLLECT_BATCH]
    return batch, recollecting, stale


def _recollect_context(npc: dict) -> tuple[dict, dict]:
    known = persona.knows(npc)
    fold = [e["text"] for e in known["episodes"][:max(0, len(known["episodes"]) - persona.EPISODES_KEPT + 1)]]
    context = {"character": {"name": npc["name"], "role": minds.card(npc)["role"]}, "notes": list(known["notes"]),
               "long_memory": known.get("long_memory", ""), "to_fold": fold}
    fallback = {"episode": " ".join(known["notes"])[:400],
                "long_memory": " ".join(filter(None, [known.get("long_memory", "")] + fold))[-600:]}
    return context, fallback


def _apply_recollection(npc: dict, context: dict, result: dict, now: int) -> dict:
    """The conversation becomes an episode; the notes it covered are cleared; the oldest episodes fold away."""
    known = persona.knows(npc)
    covered = len(context["notes"])
    known["notes"] = known["notes"][covered:]
    if result["episode"]:
        known["episodes"].append({"at": now, "text": result["episode"]})
    if context["to_fold"]:
        known["episodes"] = known["episodes"][len(context["to_fold"]):]
        known["long_memory"] = result["long_memory"]
    known["since"] = now
    known["talks"] = known.get("talks", 0) + 1
    return {"npc_id": npc["id"], "kind": "recollect", "episode": result["episode"],
            "folded": len(context["to_fold"])}


@router.post("/runs/{run_id}/think")
def think(run_id: str, request: ThinkRequest):
    """Let people with something on their mind decide what to do (model calls run outside the lock)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior = connection.execute("SELECT seq FROM events WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior is not None:
            return {"state": store.state_at(connection, run, int(prior["seq"])), "duplicate": True}
        if not state.get("pending_minds"):
            return {"state": state, "duplicate": False}
        guard = (run_id, request.lane)
        if guard in _thinking_runs or (run_id, "any") in _thinking_runs or \
                (request.lane == "any" and any(r == run_id for r, _ in _thinking_runs)):
            raise HTTPException(409, {"reason": "in_progress"})
        over_budget = telemetry.calls_for_run(connection, run_id, decider=True) >= ai_config.max_decider_calls_per_run()
        writing_allowed = telemetry.calls_for_run(connection, run_id) < ai_config.max_calls_per_run()
        batch, recollecting, stale = _choose(state, request.lane)
        _thinking_runs.add(guard)
        snapshot = copy.deepcopy(state)
        # Past the decider allowance, days go on by routine and chats are small talk; reactions still decide.
        # A chance meeting with nothing to pass on is a nod, decided by code (no model call).
        ask = [p for p in batch if p["kind"] != "told" and not (over_budget and p["kind"] not in REACTING) and not (
            p["kind"] == "meet" and not village.has_news(snapshot, minds.find(snapshot["npcs"], p["npc_id"]),
                                                         minds.find(snapshot["npcs"], p["why"])))]
        shared = minds.batch_request(snapshot, ask) if ask else None
        memory_jobs = [(p, *_recollect_context(minds.find(snapshot["npcs"], p["npc_id"]))) for p in recollecting]
    records: list[dict] = []
    try:
        calls: dict[str, decider.DeciderCall] = {}
        answers: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            memory_futures = [pool.submit(voice.recollect, context, fallback, writing_allowed)
                              for _, context, fallback in memory_jobs]
            if shared:  # One request for everyone deciding now; per-person requests only for anyone it missed.
                text, questions, prefixes = shared
                batch_call = decider.decide(text, questions)
                calls["batch"] = batch_call
                for pending in ask:
                    mine = minds.answers_for(batch_call.answers, prefixes[pending["npc_id"]])
                    if batch_call.ok and minds.ANSWER_KEY[pending["kind"]] in mine:
                        answers[pending["npc_id"]] = mine
            missing = [p for p in ask if p["npc_id"] not in answers]
            for pending, call in zip(missing, decider.decide_many(
                    [minds.decision_request(snapshot, p) for p in missing])):
                calls[pending["npc_id"]] = call
                if call.ok:
                    answers[pending["npc_id"]] = call.answers
            # Two villagers talking where the stranger can see them: their own words, one call per chat.
            chats = {}
            for pending in batch:
                a = minds.find(snapshot["npcs"], pending["npc_id"])
                if pending["kind"] != "meet" or not village.chatter_allowed(snapshot, a, snapshot["sim_time_ms"]):
                    continue
                b = minds.find(snapshot["npcs"], pending["why"])
                mine = answers.get(a["id"], {})
                topic = village.topics(snapshot, a, b)[village.chosen_topic(snapshot, a, b, mine)]
                chats[a["id"]] = pool.submit(voice.chatter, village.chatter_context(snapshot, a, b, topic, mine),
                                             village.fallback_chatter(a, b, topic, mine), writing_allowed)
            hearings = {}  # Someone told something: both lines and the listener's choice, one voice call each.
            for pending in batch:
                if pending["kind"] != "told":
                    continue
                listener = minds.find(snapshot["npcs"], pending["npc_id"])
                teller = minds.find(snapshot["npcs"], pending["why"])
                if listener is None or teller is None:
                    continue
                message = str(pending.get("message", ""))
                hearings[listener["id"]] = pool.submit(
                    voice.hearing, village.hearing_context(snapshot, listener, teller, message),
                    village.fallback_hearing(listener, teller, message), writing_allowed)
            remembered = [future.result() for future in memory_futures]
            heard_back = {npc_id: future.result() for npc_id, future in hearings.items()}
            spoken = {npc_id: future.result() for npc_id, future in chats.items()}
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            for call in calls.values():
                telemetry.record(connection, run_id, "decider", call.model, call.provider, call.latency_ms, call.ok,
                                 call.error or call.fallback_from, call.input_tokens, call.output_tokens)
            for call, _ in remembered + list(spoken.values()) + list(heard_back.values()):
                if call.model and call.model != "stub" and call.status in ("ok", "fallback") and call.latency_ms:
                    telemetry.record(connection, run_id, "memory" if call.prompt_version.startswith("recollect")
                                     else "chatter", call.model, call.prompt_version, call.latency_ms,
                                     call.status == "ok", call.error, call.input_tokens, call.output_tokens)
            working = copy.deepcopy(state)
            handled = {(p["npc_id"], p["kind"]) for p in batch + recollecting + stale}
            working["pending_minds"] = [p for p in working.get("pending_minds", []) if p["kind"] in KINDS
                                        and (p["npc_id"], p["kind"]) not in handled
                                        and (n := minds.find(working["npcs"], p["npc_id"])) and n.get("alive", True)
                                        and not n.get("down")]
            now, heard, learned = working["sim_time_ms"], [], []
            for pending in batch:
                npc = minds.find(working["npcs"], pending["npc_id"])
                call = calls.get(pending["npc_id"]) or calls.get("batch")
                record = {"npc_id": pending["npc_id"], "kind": pending["kind"], "why": pending["why"],
                          "skipped": None, "shared_request": pending["npc_id"] not in calls}
                mine = answers.get(pending["npc_id"])
                if npc is None or not npc.get("alive", True):
                    record["skipped"] = "no longer alive"
                elif pending["kind"] == "agenda":
                    if village.free(working, npc):
                        record.update(village.apply_agenda(working, npc, mine or {}, now))  # No answer: carry on.
                    else:
                        record["skipped"] = "busy with something else now"
                elif pending["kind"] == "told":
                    teller = minds.find(working["npcs"], pending["why"])
                    call_result = heard_back.get(npc["id"])
                    if teller is None or call_result is None:
                        record["skipped"] = "the teller is gone"
                    else:
                        record.update(village.apply_hearing(working, npc, teller, str(pending.get("message", "")),
                                                            call_result[1], now, heard))
                        record["voice"] = call_result[0].as_dict()
                elif pending["kind"] == "meet":
                    if _meet_ready(working, pending):
                        other = minds.find(working["npcs"], pending["why"])
                        said = spoken.get(npc["id"])
                        record.update(village.apply_meeting(working, npc, other, mine or {},
                                                            said[1] if said else None, now))
                        learned += record.pop("learned")
                    else:
                        record["skipped"] = "they went their separate ways"
                elif mine is None:
                    record["skipped"] = f"decider failed: {call.error if call else 'no answer'}"
                else:
                    record.update(minds.apply_decision(working, npc, mine, now, heard))
                records.append(record)
                if pending["kind"] == "told":  # A voice call, not the decider: its context is in record["voice"].
                    situation, questions = str(pending.get("message", "")), {}
                elif shared and pending in ask and record["shared_request"]:
                    situation, questions = shared[0], {k: v for k, v in shared[1].items()
                                                       if k.startswith(shared[2][pending["npc_id"]])}
                else:
                    situation, questions = minds.decision_request(snapshot, pending)
                trace = {**record, "situation": situation, "questions": questions,
                         "call": call.as_dict() if call else {}, "people_in_request": len(ask)}
                if pending["kind"] == "meet" and spoken.get(pending["npc_id"]):
                    trace["chatter"] = spoken[pending["npc_id"]][0].as_dict()
                connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                   (run_id, state["event_seq"] + 1, pending["npc_id"], json.dumps(trace)))
            for (pending, context, _), (call, result) in zip(memory_jobs, remembered):
                npc = minds.find(working["npcs"], pending["npc_id"])
                if npc is None:
                    continue
                record = _apply_recollection(npc, context, result, now)
                records.append(record)
                connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                   (run_id, state["event_seq"] + 1, npc["id"], json.dumps(
                                       {**record, "why": "the conversation ended", "notes": context["notes"],
                                        "voice": call.as_dict()})))
            payload = {"npcs": working["npcs"], "player": working["player"],
                       "pending_minds": working.get("pending_minds", []), "people_journal": heard,
                       "decisions": records, "encounter": working.get("encounter"), "fight": working.get("fight"),
                       "learned_added": learned,
                       "village": working.get("village", state.get("village", {"chatter_at": []}))}
            store.append(connection, state, "minds", payload, request.request_id, state["tick"])
            state["npcs"], state["player"] = payload["npcs"], payload["player"]
            store.apply_people(state, payload)
    finally:
        _thinking_runs.discard(guard)
    response = {"state": state, "duplicate": False}
    if run["mode"] == "developer":
        response["decisions"] = records
    return response
