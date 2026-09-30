"""Filling, showing and giving (judge v6), with the judge stubbed: what code allows, commits and who sees it."""

import pytest
from test_craft import commit, fresh_state, judged

import crafting
import minds
import talk


def carry(state, *ids):
    for item in ids:
        state["objects"][item]["holder_id"] = "player"


def fill(container, source, litres=1.0):
    return judged("fill", fill={"container_id": container, "source_id": source, "litres": litres})


def show(object_id, observed, works=True, used=(), audience=(), results=()):
    return judged(
        "demonstrate",
        demonstration={
            "object_id": object_id,
            "used_ids": list(used),
            "audience_ids": list(audience),
            "observed": observed,
            "works": works,
            "capabilities": [{"text": t, "status": s} for t, s in results],
        },
    )


def give(items, recipient):
    return judged("give", give={"item_ids": list(items), "recipient_id": recipient})


def water_total(state):
    return sum(o.get("water_l", 0.0) for o in state["objects"].values()) + state.get("water_spilled_l", 0.0)


def test_water_is_filled_from_a_source_and_conserved():
    state = fresh_state(34, 53)  # By Hessa's bowl (32, 52) and trough (36, 52).
    before = water_total(state)
    context = crafting.build_context(state, "fill the bowl", [])
    assert [w["id"] for w in context["water_sources"]] == ["trough_hessa"]
    bowl = next(i for i in context["available_items"] if i["id"] == "bowl_hessa")
    assert bowl["capacity_l"] == 1.0 and bowl["water_l"] == 0.0
    summary = commit(state, fill("bowl_hessa", "trough_hessa", litres=5))  # Only 1 L fits.
    assert summary["category"] == "success" and state["objects"]["bowl_hessa"]["water_l"] == 1.0
    assert state["objects"]["trough_hessa"]["water_l"] == 79.0 and water_total(state) == pytest.approx(before)
    assert {c["id"] for c in summary["property"]} == {"bowl_hessa", "trough_hessa"}  # Hessa's things, used.
    full = crafting.validate(state, fill("bowl_hessa", "trough_hessa"))
    assert full["category"] == "blocked" and "already full" in full["reason"]
    assert crafting.validate(state, fill("flint_a", "trough_hessa"))["category"] == "unresolved"  # Not at hand.


def compass(state):
    """A magnetised needle floating in a bowl of water, made from real inputs."""
    carry(state, "needles_mara", "bowl_hessa", "leaves_a")
    state["objects"]["bowl_hessa"]["water_l"] = 1.0
    state["objects"]["trough_hessa"]["water_l"] -= 1.0  # As if filled from the trough.
    spec = {
        "name": "water compass",
        "description": "A magnetised needle on a leaf floating in a bowl of water.",
        "materials": ["iron", "leaf", "fired clay"],
        "consumes": ["needles_mara", "leaves_a", "bowl_hessa"],
        "tools_used": ["lodestone_darin"],
        "mass_kg": 0.5,
        "length_m": None,
        "capacity_l": 1.0,
        "rated_load_kg": None,
        "flags": ["container", "watertight", "magnetized", "indicates_direction"],
        "capabilities": [{"text": "points the same way every time", "status": "expected"}],
    }
    carry(state, "lodestone_darin")
    return commit(state, judged("make", new_object=spec), text="make a water compass")


def test_water_goes_into_what_is_made_and_magnets_need_a_magnet():
    state = fresh_state(34, 53)
    before = water_total(state)
    summary = compass(state)
    made = state["objects"][summary["steps"] and state["last_action"]["made"]]
    assert "magnetized" in made["flags"] and made["water_l"] == 1.0  # The lodestone made it possible.
    assert water_total(state) == pytest.approx(before)


def test_showing_updates_what_it_is_known_to_do_and_who_saw_it():
    state = fresh_state(34, 53)
    compass(state)
    made = state["last_action"]["made"]
    hessa = next(n for n in state["npcs"] if n["id"] == "npc_hessa_marr")
    hessa.update(x=33, y=53)
    far = next(n for n in state["npcs"] if n["id"] == "npc_mara_venn")
    seen = "The stranger turned the bowl; the needle swung back to point the same way, three times."
    state["event_seq"] += 1
    commit(
        state,
        show(made, seen, audience=["npc_hessa_marr"], results=[("points the same way every time", "observed")]),
        text="show Hessa",
    )
    entry = state["last_action"]
    hessa = minds.find(state["npcs"], "npc_hessa_marr")  # The committed world has fresh records.
    assert entry["demonstration"]["observed"] == seen
    known = state["objects"][made]["known_capabilities"]
    assert known[0]["status"] == "observed" and known[0]["event_id"] == entry["event_id"]
    perceptions = minds.perceive(state, entry)
    by = {p["npc_id"]: p for p in perceptions}
    assert by["npc_hessa_marr"]["memory"]["summary"] == seen and by["npc_hessa_marr"]["memory"]["source"] == "shown"
    assert far["id"] not in by
    state.setdefault("pending_minds", [])
    minds.apply_perceptions(state, [p for p in perceptions if p["memory"]["kind"] == "demonstration"])
    assert not state["pending_minds"]  # Seeing something shown is remembered, not an alarm.
    # What she saw is evidence: she can now come to trust the stranger beyond what words earn.
    for _ in range(10):
        talk._update_regard(hessa, {"impression": {"score": 4}, "suspicion": {"score": 0}})
    assert talk.regard(hessa)["trust"] > 0.4 + talk.TALK_GOODWILL


def test_a_failed_showing_is_seen_but_earns_nothing():
    state = fresh_state(34, 53)
    carry(state, "potshard_a")
    hessa = next(n for n in state["npcs"] if n["id"] == "npc_hessa_marr")
    hessa.update(x=33, y=53)
    commit(
        state,
        show(
            "potshard_a",
            "The stranger held up a pot shard and waited; nothing happened.",
            works=False,
            audience=["npc_hessa_marr"],
        ),
        text="show Hessa the magic shard",
    )
    state.setdefault("pending_minds", [])
    minds.apply_perceptions(state, minds.perceive(state, state["last_action"]))
    hessa = minds.find(state["npcs"], "npc_hessa_marr")
    assert hessa["mind"]["memories"][-1]["works"] is False
    for _ in range(10):
        talk._update_regard(hessa, {"impression": {"score": 4}})
    assert talk.regard(hessa)["trust"] <= 0.4 + talk.TALK_GOODWILL + 1e-9


def test_giving_hands_things_over_and_the_receiver_notices():
    state = fresh_state()
    tomas = next(n for n in state["npcs"] if n["id"] == "npc_tomas_reed")
    state["player"].update(x=tomas["x"], y=tomas["y"] + 1)
    carry(state, "flint_a")
    blocked = crafting.validate(state, give(["branch_a"], "npc_tomas_reed"))
    assert blocked["category"] == "blocked" and "aren't carrying" in blocked["reason"]
    summary = commit(state, give(["flint_a"], "npc_tomas_reed"), text="give Tomas the flint")
    assert summary["category"] == "success"
    assert state["objects"]["flint_a"]["holder_id"] == "npc_tomas_reed"
    assert state["objects"]["flint_a"]["owner_id"] == "npc_tomas_reed"  # A gift of something unowned.
    assert "flint_a" not in {i["id"] for i in crafting.available_items(state)}
    perceptions = minds.perceive(state, state["last_action"])
    mine = next(p for p in perceptions if p["npc_id"] == "npc_tomas_reed")
    assert mine["memory"]["kind"] == "gift" and mine["memory"]["source"] == "received" and not mine["think"]
    assert mine["memory"]["short"] == "gave me a flint shard"
