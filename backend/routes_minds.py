"""People thinking: everyone with something on their mind decides, in one Jev request."""
from __future__ import annotations

import copy
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import encounter
import minds
import store
from ai import decider, telemetry

router = APIRouter()


class ThinkRequest(BaseModel):
    expected_version: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)


_thinking_runs: set[str] = set()


@router.post("/runs/{run_id}/think")
def think(run_id: str, request: ThinkRequest):
    """Let people with something on their mind decide what to do (the decider runs outside the lock)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        prior = connection.execute("SELECT seq FROM events WHERE run_id=? AND request_id=?",
                                   (run_id, request.request_id)).fetchone()
        if prior is not None:
            return {"state": store.state_at(connection, run, int(prior["seq"])), "duplicate": True}
        # Reactions to what they saw, and intents for encounter rounds ("resolve_attack" is from older saves).
        batch = [p for p in state.get("pending_minds", []) if p["kind"] in ("decide", "round")
                 and (npc := minds.find(state["npcs"], p["npc_id"])) and npc.get("alive", True)][:minds.THINK_BATCH]
        if not state.get("pending_minds"):
            return {"state": state, "duplicate": False}
        if run_id in _thinking_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        _thinking_runs.add(run_id)
        shared = minds.batch_request(state, batch) if batch else None
    try:
        # One request for everyone deciding now; per-person requests only for anyone it left out.
        calls: dict[str, decider.DeciderCall] = {}
        answers: dict[str, dict] = {}
        if shared:
            text, questions, prefixes = shared
            batch_call = decider.decide(text, questions)
            calls["batch"] = batch_call
            for pending in batch:
                mine = minds.answers_for(batch_call.answers, prefixes[pending["npc_id"]])
                if batch_call.ok and "action" in mine:
                    answers[pending["npc_id"]] = mine
        missing = [pending for pending in batch if pending["npc_id"] not in answers]
        with store.lock, store.db() as connection:
            _, snapshot = store.load_run(connection, run_id)
        for pending, call in zip(missing, decider.decide_many(
                [minds.decision_request(snapshot, pending) for pending in missing])):
            calls[pending["npc_id"]] = call
            if call.ok:
                answers[pending["npc_id"]] = call.answers
        with store.lock, store.db() as connection:
            run, state = store.load_run(connection, run_id)
            for call in calls.values():
                telemetry.record(connection, run_id, "decider", call.model, call.provider, call.latency_ms, call.ok,
                                 call.error or call.fallback_from, call.input_tokens, call.output_tokens)
            working = copy.deepcopy(state)
            handled = {(p["npc_id"], p["kind"]) for p in batch}
            working["pending_minds"] = [p for p in working.get("pending_minds", [])
                                        if p["kind"] in ("decide", "round") and (p["npc_id"], p["kind"]) not in handled]
            now, heard, records = working["sim_time_ms"], [], []
            for pending in batch:
                npc = minds.find(working["npcs"], pending["npc_id"])
                call = calls.get(pending["npc_id"]) or calls.get("batch")
                record = {"npc_id": pending["npc_id"], "kind": pending["kind"], "why": pending["why"],
                          "skipped": None, "shared_request": pending["npc_id"] not in calls}
                if npc is None or not npc.get("alive", True):
                    record["skipped"] = "no longer alive"
                elif pending["npc_id"] not in answers:
                    record["skipped"] = f"decider failed: {call.error if call else 'no answer'}"
                elif pending["kind"] == "round":
                    if pending["npc_id"] in encounter.missing_intents(working):
                        record.update(encounter.set_intent(working, npc, answers[pending["npc_id"]]))
                    else:
                        record["skipped"] = "already committed this round"
                else:
                    record.update(minds.apply_decision(working, npc, answers[pending["npc_id"]], now, heard))
                records.append(record)
                situation, questions = (shared[0], {k: v for k, v in shared[1].items()
                                                    if k.startswith(shared[2][pending["npc_id"]])}) \
                    if record["shared_request"] and shared else minds.decision_request(snapshot, pending)
                trace = {**record, "situation": situation, "questions": questions,
                         "call": call.as_dict() if call else {}, "people_in_request": len(batch)}
                connection.execute("INSERT INTO mind_traces (run_id,event_seq,npc_id,trace_json) VALUES (?,?,?,?)",
                                   (run_id, state["event_seq"] + 1, pending["npc_id"], json.dumps(trace)))
            payload = {"npcs": working["npcs"], "player": working["player"],
                       "pending_minds": working.get("pending_minds", []), "people_journal": heard,
                       "decisions": records, "encounter": working.get("encounter")}
            store.append(connection, state, "minds", payload, request.request_id, state["tick"])
            state["npcs"], state["player"] = payload["npcs"], payload["player"]
            store.apply_people(state, payload)
    finally:
        _thinking_runs.discard(run_id)
    response = {"state": state, "duplicate": False}
    if run["mode"] == "developer":
        response["decisions"] = records
    return response
