"""The gate bar (GDD D-42): a physical way in. Lifting the cracked bar off the gate is a judged deed like any
other; guards who see it treat it as an assault on the gate and fight, and a guard near the gate steps into the
gap. If they're dead, down or elsewhere, the stranger walks in."""
import pytest

import combat
import crafting
import minds
import talk
import village
from test_craft import commit, fresh_state, judged
from test_encounter import post, world  # noqa: F401
from test_talk import npc


@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)


def lift_out(aids=("crates_gate", "trestles_gate")):
    return judged("lift_out", effort_seconds=60, lift_out={"object_id": "gate_bar", "aid_ids": list(aids)})


def at_the_gate(state):
    state["player"].update(x=50, y=10)
    return state


def test_the_gate_starts_barred_and_opens_when_the_bar_is_off():
    state = at_the_gate(fresh_state())
    assert state["objects"]["gate_bar"]["installed_in"] == "gate_brackets" and crafting.m2.gate_barred(state)
    view = next(i for i in crafting.build_context(state, "x", [])["available_items"] if i["id"] == "gate_bar")
    assert view["installed_in"] == "gate_brackets"  # The judge sees what the bar is doing.
    commit(state, lift_out())
    assert state["gate_open"] and state["gate_unbarred_by"] == "player" and not crafting.m2.gate_barred(state)


def test_guards_who_see_it_fight_and_the_captain_will_never_let_you_in():
    state = at_the_gate(fresh_state())
    commit(state, lift_out())
    seen = minds.perceive(state, state["last_action"])
    minds.apply_perceptions(state, seen)
    roderic = npc(state, "npc_roderic_vale")
    memory = next(m for m in roderic["mind"]["memories"] if m["kind"] == "breach")
    assert memory["kind"] == "breach" and memory["severity"] == 3 and "unbarred" in memory["summary"]
    assert "npc_roderic_vale" in state["fight"]["attackers"] and len(state["fight"]["attackers"]) >= 2
    assert any("gate" in (n["mind"].get("said") or {}).get("text", "").lower() for n in state["npcs"] if n.get("mind"))
    assert talk.knows_a_crime(roderic) and not talk.can_admit(state, roderic)


def test_doing_tomas_s_swap_is_work_not_an_assault():
    state = at_the_gate(fresh_state())
    state["agreements"] = {"deal_1": {"id": "deal_1", "type": "task_for_reward", "template": "beam_help",
                                      "issuer": "npc_tomas_reed", "status": "accepted"}}
    commit(state, lift_out())
    seen = minds.perceive(state, state["last_action"])
    minds.apply_perceptions(state, seen)
    assert all(p["memory"]["kind"] != "breach" for p in seen) and not state.get("fight")
    assert state["gate_open"]  # Still, the gate stands open while the old bar is down.


def test_a_guard_near_the_gate_holds_the_gap_but_not_when_down_or_away():
    state = at_the_gate(fresh_state())
    commit(state, lift_out())
    assert combat.gate_held_by(state)["id"] == "npc_roderic_vale"  # The nearest.
    for guard in ("npc_roderic_vale", "npc_bren_marr", "npc_oren_dast"):
        npc(state, guard)["down"] = True
    npc(state, "npc_elin_west").update(x=20, y=40)
    npc(state, "npc_kade_east").update(x=60, y=50)
    assert combat.gate_held_by(state) is None
    state["admitted"] = {"by": "npc_roderic_vale"}
    npc(state, "npc_roderic_vale")["down"] = False
    assert combat.gate_held_by(state) is None  # Let in: nobody stops you.


def test_through_the_unbarred_gate_over_http(world, monkeypatch):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    for y in range(67, 8, -1):
        state = post(world, state, "move", {"x": 48, "y": y})["state"]
    world.rulings.append({"clarifying_question": None, "precedent_key": "p", "steps": [lift_out()]})
    state = post(world, state, "craft", {"text": "lever the bar off the gate on the crates", "selected_ids": []})["state"]
    assert state["gate_open"] and state["fight"]  # Seen: the guards come for you.
    while (state["player"]["x"], state["player"]["y"]) != (48, 9):  # Back beside the gate (the lift walked us).
        x, y = state["player"]["x"], state["player"]["y"]
        state = post(world, state, "move", {"x": x + (48 > x) - (48 < x), "y": y + (9 > y) - (9 < y)})["state"]
    blocked = post(world, state, "move", {"x": 48, "y": 8}, status=403)
    assert "steps into the gateway" in blocked["detail"]
    monkeypatch.setattr(combat, "gate_held_by", lambda state: None)  # Say they were all elsewhere.
    cells = [[48, y] for y in range(8, 2, -1)]  # Nothing moved: the same state as before the blocked step.
    body = post(world, state, "move", {"cells": cells})
    state = body["state"]
    assert state["inside_city"] and state["entered_by"] == "unbarred"
    assert world.http.get(f"/runs/{state['run_id']}").json()["entered_by"] == "unbarred"
