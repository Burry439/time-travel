"""Real-time fights (GDD D-41): no rounds, no dice. Blows land if you're still in reach when the wind-up ends;
damage is fixed by weapon against armour; code keeps the armour law over the judge's first strike."""
import copy

import pytest

import combat
import crafting
import minds
import village
from test_craft import commit, judged
from test_encounter import post, world  # noqa: F401
from test_heat import bowl_of_water, change
from test_talk import npc, unit_state


@pytest.fixture(autouse=True)
def quiet_village(monkeypatch):
    monkeypatch.setattr(village, "schedule", lambda state, npcs, now: None)


SPOTS = [(49, 60), (47, 60), (48, 61), (48, 59)]  # Arm's reach around the stranger.


def open_ground(state, *people):
    """The stranger on the open south road with these people beside them."""
    state["player"].update(x=48, y=60)
    for spot, npc_id in zip(SPOTS, people):
        npc(state, npc_id).update(x=spot[0], y=spot[1])
    return state


def beat(state, ms=500):
    state["npcs"], heard, state["player"] = minds.advance_world(state, ms, state["sim_time_ms"])
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)
    return heard


def test_a_swing_lands_if_you_stay_and_misses_if_you_step_out_of_reach():
    stay = open_ground(unit_state(), "npc_bren_marr")
    combat.start(stay, ["npc_bren_marr"], 0, "test", lethal=True)
    beat(stay)  # In reach: he winds up.
    swing = stay["fight"]["swings"]["npc_bren_marr"]
    assert swing["lands_at"] - swing["started"] == combat.WEAPONS["spear"]["windup_ms"]
    for _ in range(3):
        beat(stay)
    assert stay["player"]["health"] == 100 - combat.WEAPONS["spear"]["damage"]  # Fixed: no roll.
    dodge = open_ground(unit_state(), "npc_bren_marr")
    combat.start(dodge, ["npc_bren_marr"], 0, "test", lethal=True)
    beat(dodge)
    dodge["player"].update(x=44)  # Step away while he's winding up.
    heard = beat(dodge) + beat(dodge)
    assert dodge["player"].get("health", 100) == 100 and any(h["category"] == "miss" for h in heard)


def test_a_sword_wounds_the_unarmoured_stranger_badly_and_a_second_blow_kills():
    state = open_ground(unit_state(), "npc_roderic_vale")
    combat.start(state, ["npc_roderic_vale"], 0, "test", lethal=True)
    for _ in range(20):
        beat(state)
        if not state["player"]["alive"]:
            break
    assert not state["player"]["alive"] and state["fight"] is None
    blows = [e["category"] for e in state["journal"] if e.get("kind") == "fight" and e["category"] != "miss"]
    assert blows == ["hit", "killed"]


def test_the_same_fight_always_goes_the_same_way():
    first = open_ground(unit_state(), "npc_bren_marr", "npc_oren_dast")
    combat.start(first, ["npc_bren_marr", "npc_oren_dast"], 0, "test")
    second = copy.deepcopy(first)
    for state in (first, second):
        for _ in range(8):
            beat(state)
            state["player"]["x"] -= 1 if state["sim_time_ms"] % 2000 == 0 else 0
    assert first["player"] == second["player"] and first["fight"] == second["fight"]


def test_fists_do_nothing_to_mail_a_little_to_padding_and_hurt_the_unarmoured():
    state = open_ground(unit_state(), "npc_bren_marr", "npc_kade_east")
    npc(state, "npc_hessa_marr").update(x=48, y=61)
    combat.start(state, ["npc_bren_marr", "npc_kade_east", "npc_hessa_marr"], 0, "test")
    assert combat.punch(state, "npc_bren_marr", 0)["result"] == "glanced"
    assert npc(state, "npc_bren_marr").get("health", 100) == 100
    assert not combat.punch(state, "npc_kade_east", 100)["ok"]  # Still recovering from the last swing.
    assert combat.punch(state, "npc_kade_east", 1000)["result"] == "hit"
    assert npc(state, "npc_kade_east")["health"] == 100 - combat.PUNCH["padded"]
    for n in range(5):
        result = combat.punch(state, "npc_hessa_marr", 2000 + n * 1000)["result"]
    assert result == "down" and npc(state, "npc_hessa_marr")["down"] and npc(state, "npc_hessa_marr")["alive"]
    assert "npc_hessa_marr" not in state["fight"]["attackers"]
    assert combat.punch(state, "npc_hessa_marr", 9000)["ok"] is False  # Nobody to hit: she's down.


def test_it_ends_when_every_attacker_is_down_or_the_stranger_gets_away():
    state = open_ground(unit_state(), "npc_jory_venn")
    combat.start(state, ["npc_jory_venn"], 0, "test")
    for n in range(6):
        combat.punch(state, "npc_jory_venn", n * 1000)
    assert state["fight"] is None and npc(state, "npc_jory_venn")["down"]
    beat(state, 1000)
    assert (npc(state, "npc_jory_venn")["x"], npc(state, "npc_jory_venn")["y"]) == (49, 60)  # Stays down.
    away = open_ground(unit_state(), "npc_mara_venn")
    combat.start(away, ["npc_mara_venn"], 0, "test")
    away["player"].update(x=48, y=60)
    npc(away, "npc_mara_venn").update(x=48 + int(minds.GIVE_UP_CELLS) + 2, y=60)
    heard = beat(away)
    assert away["fight"] is None and any(h["category"] == "gives_up" for h in heard)


# --- The first strike: judged physics, with the armour law --------------------------------------

def test_a_wooden_spear_glances_off_mail_but_kills_an_unarmoured_man():
    spear = {"name": "sharpened stake", "description": "A pointed stake.", "materials": ["wood"], "mass_kg": 1.2}
    state = unit_state()
    guard = npc(state, "npc_bren_marr")
    state["player"].update(x=guard["x"], y=guard["y"] + 1)
    state["objects"]["branch_a"].update(holder_id="player", **spear)
    summary = commit(state, judged("harm", harm={"target_id": "npc_bren_marr", "weapon_id": "branch_a",
                                                 "method": "melee", "result": "killed", "injury": "run through"}))
    assert summary["harm"]["result"] == "deflected" and npc(state, "npc_bren_marr")["alive"]
    state = unit_state()
    tomas = npc(state, "npc_tomas_reed")
    state["player"].update(x=tomas["x"], y=tomas["y"] + 1)
    state["objects"]["branch_a"].update(holder_id="player", **spear)
    summary = commit(state, judged("harm", harm={"target_id": "npc_tomas_reed", "weapon_id": "branch_a",
                                                 "method": "melee", "result": "killed", "injury": "run through"}))
    assert summary["harm"]["result"] == "killed" and not npc(state, "npc_tomas_reed")["alive"]


def test_boiling_water_disables_a_guard_and_the_others_come_for_you():
    state = unit_state()
    state["player"].update(x=37, y=53)  # By the inn's fire and trough.
    bowl_of_water(state)
    commit(state, judged("change", change=change("bowl_hessa", temperature="boiling", heat_source_id="cookfire_hessa")))
    bren, oren = npc(state, "npc_bren_marr"), npc(state, "npc_oren_dast")
    bren.update(x=38, y=54)
    oren.update(x=40, y=53)
    assert crafting.people_nearby(state)[0]["armour"]  # The judge sees what they wear...
    view = {p["id"]: p for p in crafting.people_nearby(state)}
    assert "mail" in view["npc_bren_marr"]["armour"] and "aware_of_you" in view["npc_bren_marr"]
    payload, summary, after = crafting.resolve_attempt(
        state, "unit0000", "throw the boiling water in Bren's face", {"clarifying_question": None,
        "precedent_key": "p", "steps": [judged("harm", harm={"target_id": "npc_bren_marr", "weapon_id": "bowl_hessa",
                                                             "method": "poured", "result": "disabled",
                                                             "injury": "scalded face"})]}, None, "t", 0)
    assert summary["harm"]["result"] == "disabled"  # ...but boiling water gets past mail.
    down = minds.find(after["npcs"], "npc_bren_marr")
    assert down["alive"] and down["down"] and down["controller"]["activity"] == "down"
    minds.apply_perceptions(after, minds.perceive(after, payload["journal_entry"]))
    assert after["fight"]["attackers"] == ["npc_oren_dast"]  # Oren saw it: he comes at you at once.


# --- Over HTTP ------------------------------------------------------------------------------------

def test_space_is_a_code_only_punch_that_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    assert post(world, state, "strike", {}, status=409)["detail"]["reason"] == "no_target"  # Nobody within reach.
    while (state["player"]["x"], state["player"]["y"]) != (36, 52):  # Beside Hessa at the inn.
        px, py = state["player"]["x"], state["player"]["y"]
        state = post(world, state, "move", {"x": px + (36 > px) - (36 < px), "y": py + (52 > py) - (52 < py)})["state"]
    world.rulings.append({"clarifying_question": None, "precedent_key": "p", "steps": [judged(
        "harm", harm={"target_id": "npc_hessa_marr", "weapon_id": None, "method": "melee", "result": "wounded",
                      "injury": "a bruise"})]})
    state = post(world, state, "craft", {"text": "punch Hessa", "selected_ids": []})["state"]
    world.intents.append("attack")
    reply = world.http.post(f"/runs/{state['run_id']}/think", json={
        "expected_version": state["event_seq"], "request_id": "think-1"})
    state = reply.json()["state"]
    assert reply.status_code == 200, reply.text
    assert state["fight"]["attackers"] == ["npc_hessa_marr"]  # She chose to fight back.
    body = post(world, state, "strike", {"target_id": "npc_hessa_marr"})
    assert body["strike"]["result"] in ("hit", "missed") and body["state"]["event_seq"] == state["event_seq"] + 1
    state = body["state"]
    assert world.http.get(f"/runs/{state['run_id']}").json() == state


def test_space_outside_a_fight_is_an_assault_like_any_other():
    guard = open_ground(unit_state(), "npc_bren_marr")
    assert combat.punch(guard, "npc_bren_marr", 0)["result"] == "glanced"  # Mail: it does nothing...
    assert "npc_bren_marr" in guard["fight"]["attackers"]  # ...but it's an attack on a guard: a fight.
    villager = open_ground(unit_state(), "npc_hessa_marr")
    assert combat.punch(villager, "npc_hessa_marr", 0)["result"] == "hit"
    hessa = npc(villager, "npc_hessa_marr")
    assert hessa["health"] == 100 - combat.PUNCH["none"] and not villager.get("fight")
    assert hessa["mind"]["memories"][-1]["kind"] == "violence"  # She remembers, and decides what to do (the decider).
    assert any(p["npc_id"] == "npc_hessa_marr" and p["kind"] == "decide" for p in villager["pending_minds"])
