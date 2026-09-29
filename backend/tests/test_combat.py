"""Real-time fights (GDD D-41, D-49): no rounds, no dice. Blows land if you're still in reach when the wind-up
ends; what they do is the weapon against the armour (gear.json); code keeps the armour law over the judge."""
import copy

import pytest

import combat
import crafting
import gear
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
    for obj in state.pop("people_objects_added", []):
        state["objects"][obj["id"]] = obj
    for object_id, fields in state.pop("people_objects_changed", {}).items():
        state["objects"][object_id].update(fields)
    state["sim_time_ms"] += ms
    state["journal"].extend(heard)
    return heard


def swing(state, target, hand="right", ms=500):
    """The stranger's blow: started now, landed on the clock."""
    result = combat.strike(state, hand, target, state["sim_time_ms"])
    if result["ok"]:
        for _ in range(6):
            beat(state, ms)
            if hand not in (state["player"].get("swings") or {}):
                break
    return result


def arm(state, oid, name, materials, mass, cls, hand="right", length=None, flags=("rigid",), kind="weapon"):
    """Put a thing in the stranger's hand."""
    state["objects"][oid] = {"id": oid, "name": name, "materials": materials, "mass_kg": mass, "length_m": length,
                             "flags": list(flags), "holder_id": "player", "capabilities": ["carry"], "bound_to": [],
                             "water_l": 0.0, "capacity_l": 0.0, "condition": "usable", "x": 0, "y": 0,
                             "gear": {"kind": kind, "class": cls, "covers": [], "quality": "fair"}}
    assert gear.equip(state, state["player"], state["objects"][oid], hand)["ok"]
    return state["objects"][oid]


def test_a_swing_lands_if_you_stay_and_misses_if_you_step_out_of_reach():
    stay = open_ground(unit_state(), "npc_bren_marr")
    combat.start(stay, ["npc_bren_marr"], 0, "test", lethal=True)
    beat(stay)  # In reach: he winds up.
    started = stay["fight"]["swings"]["npc_bren_marr"]
    spear = combat.npc_weapon(stay, npc(stay, "npc_bren_marr"))
    assert spear["class"] == "short_spear" and started["lands_at"] - started["started"] == spear["windup_ms"]
    for _ in range(3):
        beat(stay)
    struck = 100 - stay["player"]["health"]
    assert 40 <= struck <= 50  # An iron spear through travelling clothes: fixed, no roll...
    assert any(c["kind"] == "bleeding" for c in stay["player"]["conditions"])  # ...and it bleeds.
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
    swing(state, "npc_bren_marr")
    assert npc(state, "npc_bren_marr").get("health", 100) == 100  # Mail: a fist does nothing.
    assert not combat.strike(state, "right", "npc_kade_east", state["sim_time_ms"])["ok"]  # Still recovering.
    state = open_ground(unit_state(), "npc_kade_east")
    swing(state, "npc_kade_east")
    assert npc(state, "npc_kade_east")["health"] == pytest.approx(100 - 2 * 10 * (1 - 0.35), abs=0.1)  # Padding
    # softens it (and he wasn't expecting it: twice as hard).
    state = open_ground(unit_state(), "npc_hessa_marr")
    swing(state, "npc_hessa_marr", hand="left")  # Left and right fists alike.
    assert npc(state, "npc_hessa_marr")["health"] == 100 - 2 * 10  # Unarmoured, and not expecting it.


def test_it_ends_when_every_attacker_is_down_or_the_stranger_gets_away():
    state = open_ground(unit_state(), "npc_jory_venn")
    combat.start(state, ["npc_jory_venn"], 0, "test")
    arm(state, "rock_test", "hand stone", ["stone"], 2.0, "hand_stone")
    for _ in range(8):
        state["sim_time_ms"] += 700
        swing(state, "npc_jory_venn")
        if state["fight"] is None:
            break
    assert state["fight"] is None and npc(state, "npc_jory_venn")["down"]
    where = (npc(state, "npc_jory_venn")["x"], npc(state, "npc_jory_venn")["y"])
    beat(state, 1000)
    assert (npc(state, "npc_jory_venn")["x"], npc(state, "npc_jory_venn")["y"]) == where  # Stays down.
    away = open_ground(unit_state(), "npc_mara_venn")
    combat.start(away, ["npc_mara_venn"], 0, "test")
    away["player"].update(x=48, y=60)
    npc(away, "npc_mara_venn").update(x=48 + int(minds.GIVE_UP_CELLS) + 2, y=60)
    heard = beat(away)
    assert away["fight"] is None and any(h["category"] == "gives_up" for h in heard)


def test_an_iron_sword_in_hand_cuts_the_unarmoured_and_mail_turns_it():
    state = open_ground(unit_state(), "npc_darin_ko", "npc_bren_marr")
    arm(state, "sword_test", "iron sword", ["iron", "wood"], 1.3, "long_sword", length=1.0,
        flags=("rigid", "sharp_edge"))
    swing(state, "npc_darin_ko")  # He wasn't expecting it: twice as bad.
    assert not npc(state, "npc_darin_ko")["alive"]
    state["sim_time_ms"] += 2000
    swing(state, "npc_bren_marr")
    bren = npc(state, "npc_bren_marr")
    assert bren["alive"] and bren["health"] > 80  # Mail: the cut barely gets through.


def test_a_raised_shield_takes_blows_from_the_front_but_not_behind():
    state = open_ground(unit_state(), "npc_bren_marr")
    arm(state, "shield_test", "round shield", ["wood", "iron"], 4.0, "round", hand="left", kind="shield")
    combat.start(state, ["npc_bren_marr"], 0, "test", lethal=True)
    bren = npc(state, "npc_bren_marr")
    towards = [bren["x"] - 48, bren["y"] - 60]
    assert combat.guard(state, True, towards, 0)["ok"]
    for _ in range(4):
        beat(state)
    assert state["player"].get("health", 100) == 100 and state["objects"]["shield_test"]["shield_hp"] < 90
    assert not combat.strike(state, "left", "npc_bren_marr", state["sim_time_ms"])["ok"]  # That hand holds it up.
    combat.guard(state, True, [-towards[0], -towards[1]], state["sim_time_ms"])  # Facing away.
    for _ in range(4):
        beat(state)
    assert state["player"]["health"] < 100


def test_two_handed_weapons_take_both_hands_and_x_swaps():
    state = unit_state()
    spear = arm(state, "pike_test", "long spear", ["wood", "iron"], 3.0, "long_spear", length=3.0,
                flags=("rigid", "sharp_edge"))
    kit = state["player"]["equipped"]
    assert kit["right"] == kit["left"] == spear["id"]
    assert combat.hand_free(state, "left")
    knife = arm(state, "knife_test", "knife", ["iron"], 0.3, "knife", hand="left", length=0.25,
                flags=("rigid", "sharp_edge"))
    assert kit.get("right") is None and kit["left"] == knife["id"]  # The pike had to go.
    assert gear.swap_hands(state, state["player"])["ok"] and kit["right"] == knife["id"]


def test_an_arrow_flies_hits_and_lands_where_it_can_be_picked_up():
    state = open_ground(unit_state())
    tomas = npc(state, "npc_tomas_reed")
    tomas.update(x=48, y=52)
    arm(state, "bow_test", "bow", ["yew", "sinew"], 0.8, "bow", flags=("flexible",))
    state["objects"]["arrows_test"] = {"id": "arrows_test", "name": "arrows", "materials": ["wood", "iron", "feather"],
                                       "mass_kg": 0.6, "flags": ["rigid", "sharp_edge"], "holder_id": "player",
                                       "capabilities": ["carry"], "bound_to": [], "water_l": 0.0, "capacity_l": 0.0,
                                       "condition": "usable", "x": 0, "y": 0, "count": 6,
                                       "gear": {"kind": "ammo", "class": "arrow", "covers": [], "quality": "fair"}}
    assert gear.equip(state, state["player"], state["objects"]["arrows_test"], "ammo")["ok"]
    assert combat.strike(state, "right", "npc_tomas_reed", 0)["ok"]
    for _ in range(6):
        beat(state)
    assert npc(state, "npc_tomas_reed")["health"] < 60
    assert state["objects"]["arrows_test"]["count"] == 5
    assert any(o["name"] == "arrow" and o["holder_id"] is None for o in state["objects"].values())


def test_bleeding_goes_on_after_the_fight_and_can_kill():
    state = open_ground(unit_state(), "npc_roderic_vale")
    combat.start(state, ["npc_roderic_vale"], 0, "test", lethal=True)
    for _ in range(4):
        beat(state)
        if state["player"].get("conditions"):
            break
    combat.finish(state, state["sim_time_ms"])
    npc(state, "npc_roderic_vale").update(x=10, y=10)
    for _ in range(40):
        beat(state, 30_000)
        if not state["player"]["alive"]:
            break
    assert not state["player"]["alive"]  # Nobody bound it.


# --- The first strike: judged physics, with the armour law --------------------------------------

def test_a_wooden_spear_glances_off_mail_but_kills_an_unarmoured_man():
    spear = {"name": "sharpened stake", "description": "A pointed stake.", "materials": ["wood"], "mass_kg": 1.2,
             "flags": ["rigid", "sharp_edge"], "length_m": 1.0}
    state = unit_state()
    guard = npc(state, "npc_bren_marr")
    state["player"].update(x=guard["x"], y=guard["y"] + 1)
    state["objects"]["branch_a"].update(holder_id="player", **spear)
    state["objects"]["branch_a"].pop("gear", None)  # (Now a stake: code reads it afresh.)
    summary = commit(state, judged("harm", harm={"target_id": "npc_bren_marr", "weapon_id": "branch_a",
                                                 "method": "melee", "result": "killed", "injury": "run through"}))
    assert summary["harm"]["result"] == "deflected" and npc(state, "npc_bren_marr")["alive"]
    state = unit_state()
    tomas = npc(state, "npc_tomas_reed")
    state["player"].update(x=tomas["x"], y=tomas["y"] + 1)
    state["objects"]["branch_a"].update(holder_id="player", **spear)
    state["objects"]["branch_a"].pop("gear", None)  # (Now a stake: code reads it afresh.)
    summary = commit(state, judged("harm", harm={"target_id": "npc_tomas_reed", "weapon_id": "branch_a",
                                                 "method": "melee", "result": "killed", "injury": "run through",
                                                 "target_area": "heart", "outcome": "landed"}))
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

def test_space_is_a_blow_on_the_clock_that_replays(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    assert post(world, state, "strike", {}, status=409)["detail"]["reason"] == "no_target"  # Nobody within reach.
    while (state["player"]["x"], state["player"]["y"]) != (35, 52):  # Beside Hessa at the inn.
        px, py = state["player"]["x"], state["player"]["y"]
        state = post(world, state, "move", {"x": px + (35 > px) - (35 < px), "y": py + (52 > py) - (52 < py)})["state"]
    body = post(world, state, "strike", {"target_id": "npc_hessa_marr", "hand": "right"})
    assert body["strike"]["ok"] and body["state"]["player"]["swings"]["right"]["target"] == "npc_hessa_marr"
    state = post(world, body["state"], "explore", {"elapsed_ms": 1000})["state"]
    hessa = next(n for n in state["npcs"] if n["id"] == "npc_hessa_marr")
    assert hessa["health"] < 100 and not state["player"].get("swings")
    assert world.http.get(f"/runs/{state['run_id']}").json() == state


def test_space_outside_a_fight_is_an_assault_like_any_other():
    guard = open_ground(unit_state(), "npc_bren_marr")
    swing(guard, "npc_bren_marr")
    assert npc(guard, "npc_bren_marr").get("health", 100) == 100  # Mail: it does nothing...
    assert "npc_bren_marr" in guard["fight"]["attackers"]  # ...but it's an attack on a guard: a fight.
    villager = open_ground(unit_state(), "npc_hessa_marr")
    swing(villager, "npc_hessa_marr")
    hessa = npc(villager, "npc_hessa_marr")
    assert hessa["health"] < 100 and not villager.get("fight")
    assert hessa["mind"]["memories"][-1]["kind"] == "violence"  # She remembers, and decides what to do (the decider).
    assert any(p["npc_id"] == "npc_hessa_marr" and p["kind"] == "decide" for p in villager["pending_minds"])
