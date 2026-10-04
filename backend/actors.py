"""Use the same physical judge and reducer for a person's free-form chosen work."""

from __future__ import annotations

import copy

import cast


def view(state, actor_id):
    if actor_id == "player":
        return state
    result = dict(state)
    result["player"] = copy.deepcopy(cast.find(state["npcs"], actor_id))
    card = cast.card(result["player"])
    result["actor_abilities"] = {
        "name": card["name"],
        "knowledge": card.get("knowledge", card.get("knows", {})),
        "combat": card.get("combat"),
        "ordinary_strength": True,
    }
    result["objects"] = {i: dict(o) for i, o in state["objects"].items()}
    for obj in result["objects"].values():
        for field in ("owner_id", "holder_id"):
            if obj.get(field) == actor_id:
                obj[field] = "player"
            elif obj.get(field) == "player":
                obj[field] = "__stranger__"
    return result


def normalize(delta, actor_id):
    if actor_id == "player":
        return delta
    for obj in delta["new_objects"]:
        obj["created_by"] = actor_id
        for field in ("owner_id", "holder_id"):
            if obj.get(field) == "player":
                obj[field] = actor_id
    if delta.get("given"):
        delta["given"]["owners"] = {
            i: actor_id if owner == "player" else "player" if owner == "__stranger__" else owner
            for i, owner in delta["given"]["owners"].items()
        }
    return delta


def perform(state, actor_id, proposal):
    import consequences

    payload, verdict, _ = consequences.resolve_attempt(
        state,
        state["run_id"],
        cast.mind(cast.find(state["npcs"], actor_id)).get("physical_intention", ""),
        proposal,
        None,
        f"npc:{actor_id}:{state['event_seq'] + 1}",
        state["sim_time_ms"],
        actor_id,
    )
    consequences.apply_payload(state, payload)
    cast.mind(cast.find(state["npcs"], actor_id)).pop("physical_intention", None)
    return verdict
