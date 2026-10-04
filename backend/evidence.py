"""Persistent facts and personal evidence. Descriptions never serve as identity."""

from __future__ import annotations

import json

import cast


def identity(memory: dict) -> str:
    if memory.get("evidence_id"):
        return memory["evidence_id"]
    # Demonstrating the same unchanged object/function again is the same proof.
    if memory.get("kind") == "demonstration" and memory.get("object_id"):
        parts = [
            "proof",
            memory.get("actor_id", "player"),
            memory["object_id"],
            memory.get("revision", 0),
            memory.get("application", "function"),
            memory.get("works", False),
        ]
    else:
        parts = [
            memory.get("kind"),
            memory.get("actor_id", "player"),
            memory.get("event"),
            memory.get("step_number", 1),
            memory.get("at", 0),
            memory.get("object_id"),
            memory.get("victim"),
            memory.get("item"),
        ]
    return "evidence:" + json.dumps(parts, sort_keys=True, separators=(",", ":"))


def remember(npc: dict, memory: dict) -> bool:
    ledger = cast.mind(npc).setdefault("evidence", {})
    key = identity(memory)
    memory["evidence_id"] = key
    prior = ledger.get(key)
    if prior:
        updated = False
        # First-hand evidence is not invalidated by somebody else's disbelief.
        for field in ("settled", "reported"):
            if memory.get(field) and not memory.get("doubted") and prior.get(field) != memory[field]:
                prior[field] = memory[field]
                updated |= field == "settled"
        if prior.get("clarity") == "clear" or memory.get("clarity") != "clear":
            return updated
    ledger[key] = memory
    return prior is None or memory.get("clarity") == "clear"


def held(npc: dict) -> list[dict]:
    return list((npc.get("mind") or {}).get("evidence", {}).values())


def record(state: dict, entry: dict, perceptions: list[dict]) -> None:
    facts = state.setdefault("facts", {})
    effect_id = ":".join(
        map(
            str,
            (
                "effect",
                entry.get("actor_id", "player"),
                entry.get("event_id"),
                entry.get("step_number", 1),
                entry.get("sim_time_ms", state.get("sim_time_ms", 0)),
            ),
        )
    )
    facts.setdefault(
        effect_id,
        {
            "id": effect_id,
            "event": entry.get("event_id"),
            "step": entry.get("step_number", 1),
            "actor": entry.get("actor_id", "player"),
            "action": entry.get("action"),
            "result": entry.get("reason", ""),
            "witnesses": sorted({p["npc_id"] for p in perceptions}),
        },
    )
    for view in perceptions:
        memory = view["memory"]
        key = identity(memory)
        fact = facts.setdefault(
            key,
            {
                "id": key,
                "event": entry.get("event_id"),
                "step": entry.get("step_number", 1),
                "actor": entry.get("actor_id", "player"),
                "kind": memory["kind"],
                "object_id": memory.get("object_id"),
                "victim": memory.get("victim"),
                "at": memory["at"],
                "witnesses": [],
            },
        )
        if view["npc_id"] not in fact["witnesses"]:
            fact["witnesses"].append(view["npc_id"])
        if memory["kind"] in ("theft", "violence", "breach"):
            state.setdefault("incidents", {}).setdefault(key, {**fact, "status": "open"})
