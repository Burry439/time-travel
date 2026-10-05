"""Combat laws and geometry missed by the original fight smoke (D-66)."""

import copy

import pytest
from test_combat import arm, beat, open_ground
from test_talk import npc, unit_state

import cast
import combat
import effects
import gear
import paths
import views


def facing(state, target):
    return combat._direction(state["player"], npc(state, target))


@pytest.mark.parametrize("action", ["strike", "throw", "guard"])
def test_bound_hands_cannot_use_either_hand(action):
    state = unit_state()
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
    arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    effects.put_state(state["player"], "bound", "hands tied", ["hands"], 10, 0, "test")
    result = (
        combat.guard(state, True, [0, 1], 0) if action == "guard" else getattr(combat, action)(state, "right", None, 0)
    )
    assert not result["ok"]


def test_throw_obeys_recovery_and_cannot_replace_a_committed_swing():
    state = unit_state()
    arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    assert combat.strike(state, "right", None, 0)["ok"]
    saved = copy.deepcopy(state["player"]["swings"])
    assert not combat.throw(state, "right", None, 0)["ok"]
    assert state["player"]["swings"] == saved
    state["player"]["swings"] = {}
    state["player"]["ready_at"] = {"right": 1000}
    assert not combat.throw(state, "right", None, 999)["ok"]
    assert combat.throw(state, "right", None, 1000)["ok"]


def test_an_explicit_target_behind_the_committed_direction_is_safe():
    state = open_ground(unit_state(), "npc_hessa_marr")
    npc(state, "npc_hessa_marr").update(x=48, y=59)
    assert combat.strike(state, "right", "npc_hessa_marr", 0, [0, 1])["ok"]
    beat(state, 500)
    assert npc(state, "npc_hessa_marr")["health"] == 100


def test_the_players_heavy_mace_keeps_a_heavy_blunt_profile_and_uses_two_hands():
    state = unit_state()
    mace = {
        "id": "mace",
        "name": "flanged mace",
        "materials": ["wood", "iron"],
        "mass_kg": 7.9,
        "length_m": 0.8,
        "flags": ["rigid"],
        "holder_id": "player",
        "condition": "usable",
    }
    mace["gear"] = gear.checked({"kind": "weapon", "class": "mace", "quality": "fair"}, mace)
    state["objects"]["mace"] = mace
    assert gear.weapon(mace)["class"] == "sledge"
    assert gear.weapon(mace)["damage"] > 60
    assert gear.equip(state, state["player"], mace, "right")["ok"]
    assert state["player"]["equipped"]["left"] == "mace"
    assert views.of(state)["gear"]["mace"]["profile"]["name"] == "flanged mace"
    mace["gear"] = {"kind": "none", "class": None, "quality": "fair"}
    assert gear.weapon(mace)["class"] == "sledge"  # Older saved inventions are read again without a migration.


def test_damaged_and_repaired_edges_change_the_same_objects_profile():
    state = unit_state()
    blade = arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    original = gear.weapon(blade)
    effects.apply(
        state,
        [{"kind": "damage", "target_id": "knife", "name": "blunted", "flags": ["sharp_edge"]}],
        0,
        "player",
        lambda _obj: None,
    )
    assert gear.weapon(blade)["type"] == "blunt" and gear.weapon(blade)["damage"] < original["damage"]
    effects.apply(
        state, [{"kind": "repair", "target_id": "knife", "flags": ["sharp_edge"]}], 1, "player", lambda _obj: None
    )
    assert gear.weapon(blade)["type"] == original["type"]
    assert gear.weapon(blade)["damage"] == original["damage"]


def test_damage_and_bound_hands_are_revalidated_at_impact():
    state = open_ground(unit_state(), "npc_hessa_marr")
    arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    combat.strike(state, "right", "npc_hessa_marr", 0)
    effects.put_state(state["player"], "bound", "hands tied", ["hands"], 10, 1, "test")
    beat(state, 500)
    assert npc(state, "npc_hessa_marr")["health"] == 100


def test_destroyed_and_shut_away_equipment_is_unavailable():
    state = unit_state()
    blade = arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    blade["condition"] = "destroyed"
    assert gear.held(state, state["player"]) is None
    assert not gear.equip(state, state["player"], blade, "right")["ok"]
    blade["condition"] = "usable"
    state["objects"]["box"] = {"id": "box", "closed": True}
    blade["inside"] = "box"
    assert gear.held(state, state["player"]) is None


def test_parry_timing_reduces_wear_and_delays_the_attacker():
    def run(raised_at):
        state = open_ground(unit_state(), "npc_bren_marr")
        arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
        combat.start(state, ["npc_bren_marr"], 0, "test", lethal=True)
        beat(state, 1)
        swing = state["fight"]["swings"]["npc_bren_marr"]
        at = swing["lands_at"]
        combat.guard(state, True, facing(state, "npc_bren_marr"), at - raised_at)
        beat(state, at - state["sim_time_ms"])
        return state, at

    parry, at = run(100)
    held, _ = run(200)
    assert parry["player"]["health"] == held["player"]["health"] == 100
    assert parry["objects"]["shield"]["shield_hp"] > held["objects"]["shield"]["shield_hp"]
    assert (
        parry["fight"]["recover"]["npc_bren_marr"]
        == at + combat.npc_weapon(parry, npc(parry, "npc_bren_marr"))["recover_ms"] + 180
    )


def test_turning_a_raised_guard_does_not_restart_the_parry_window():
    state = unit_state()
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="right")
    combat.guard(state, True, [0, 1], 0)
    combat.guard(state, True, [1, 0], 300)
    assert state["player"]["guard"]["at"] == 0
    assert state["player"]["guard"]["facing"] == [1, 0]


def test_bound_npc_cannot_wind_up_and_immobilized_npc_cannot_close():
    state = open_ground(unit_state(), "npc_bren_marr")
    bren = npc(state, "npc_bren_marr")
    effects.put_state(bren, "bound", "bound", ["hands", "move"], 10, 0, "test")
    combat.start(state, [bren["id"]], 0, "test")
    before = cast.cell(bren)
    beat(state, 1000)
    assert bren["id"] not in state["fight"]["swings"]
    assert cast.cell(npc(state, bren["id"])) == before


def test_a_model_selected_flee_job_leaves_the_fight_intact_for_everyone_else():
    state = open_ground(unit_state(), "npc_bren_marr", "npc_oren_dast")
    combat.start(state, ["npc_bren_marr", "npc_oren_dast"], 0, "test")
    cast.set_job(npc(state, "npc_bren_marr"), {"kind": "flee", "goal": [40, 60], "speed": "run"}, 0)
    beat(state, 100)
    assert state["fight"]["attackers"] == ["npc_oren_dast"]
    assert cast.mind(npc(state, "npc_bren_marr"))["job"]["kind"] == "flee"


def test_a_projectile_is_stopped_by_a_building():
    state = unit_state()
    wall = next(iter(paths.walls(gear.content.level(state)["map"])))
    x, y = wall
    start, aim = (x - 1, y), (x + 1, y)
    if paths.line_of_sight(state, start, aim):
        pytest.skip("selected edge does not cross a building")
    assert combat._flight_end(state, start, aim) != aim


def test_combat_replay_is_identical_across_clock_partitions():
    initial = open_ground(unit_state(), "npc_bren_marr", "npc_oren_dast")
    combat.start(initial, ["npc_bren_marr", "npc_oren_dast"], 0, "spar")
    whole, split = copy.deepcopy(initial), copy.deepcopy(initial)
    beat(whole, 1500)
    for duration in [100, 200, 300, 400, 500]:
        beat(split, duration)
    assert whole["player"] == split["player"]
    assert whole["fight"] == split["fight"]


@pytest.mark.parametrize("hand", ["right", "left"])
def test_each_hand_has_its_own_recovery(hand):
    state = unit_state()
    other = "left" if hand == "right" else "right"
    assert combat.strike(state, hand, None, 0)["ok"]
    assert combat.strike(state, other, None, 0)["ok"]
    assert not combat.strike(state, hand, None, 1)["ok"]
    assert set(state["player"]["swings"]) == {"right", "left"}


def test_a_guard_facing_away_does_not_block():
    state = open_ground(unit_state(), "npc_bren_marr")
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="right")
    combat.start(state, ["npc_bren_marr"], 0, "test", lethal=True)
    beat(state, 1)
    at = state["fight"]["swings"]["npc_bren_marr"]["lands_at"]
    toward = facing(state, "npc_bren_marr")
    combat.guard(state, True, [-toward[0], -toward[1]], 1)
    beat(state, at - state["sim_time_ms"])
    assert state["player"]["health"] < 100
    assert "shield_hp" not in state["objects"]["shield"]


def test_damage_between_commit_and_contact_weakens_the_actual_blow():
    def run(damage):
        state = open_ground(unit_state(), "npc_hessa_marr")
        blade = arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
        combat.strike(state, "right", "npc_hessa_marr", 0)
        if damage:
            effects.apply(
                state,
                [{"kind": "damage", "target_id": blade["id"], "name": "blunted", "flags": ["sharp_edge"]}],
                1,
                "player",
                lambda _obj: None,
            )
        beat(state, 230)
        return npc(state, "npc_hessa_marr")["health"]

    assert run(True) > run(False)


def test_a_damaged_shield_cannot_bash_at_contact_and_repair_restores_use():
    state = open_ground(unit_state(), "npc_hessa_marr")
    shield = arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield")
    combat.strike(state, "right", "npc_hessa_marr", 0)
    effects.apply(
        state,
        [{"kind": "damage", "target_id": shield["id"], "name": "holed", "flags": []}],
        1,
        "player",
        lambda _obj: None,
    )
    beat(state, 400)
    assert npc(state, "npc_hessa_marr")["health"] == 100
    effects.apply(state, [{"kind": "repair", "target_id": shield["id"], "flags": []}], 401, "player", lambda _obj: None)
    assert gear.functional(shield, shield=True)


def test_hidden_player_weapon_does_not_trigger_tactical_shield_anticipation():
    state = open_ground(unit_state(), "npc_roderic_vale")
    roderic = npc(state, "npc_roderic_vale")
    shield = arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
    shield["holder_id"] = roderic["id"]
    state["player"]["equipped"].pop("left")
    roderic.setdefault("equipped", {})["left"] = "shield"
    blade = arm(state, "blade", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    blade["hidden"] = {"by": "player"}
    combat.strike(state, "right", roderic["id"], 0)
    beat(state, 180)
    assert not (npc(state, roderic["id"]).get("guard") or {}).get("raised")


@pytest.mark.parametrize("move,keeps_fighting", [("carry_on", True), ("stop_fighting", False), ("flee", False)])
def test_individual_reconsideration_keeps_or_ends_their_fight(move, keeps_fighting):
    import minds

    state = open_ground(unit_state(), "npc_bren_marr", "npc_oren_dast")
    combat.start(state, ["npc_bren_marr", "npc_oren_dast"], 0, "test")
    bren = npc(state, "npc_bren_marr")
    minds.apply_decision(state, bren, {"action": {"choice": move}}, 0, state["journal"])
    beat(state, 100)
    assert combat.fighting(state, npc(state, "npc_bren_marr")) == keeps_fighting
    assert combat.fighting(state, npc(state, "npc_oren_dast"))


def test_reconsideration_receives_own_fight_and_only_visible_carried_equipment(monkeypatch):
    import routes_minds
    from ai import voice

    state = open_ground(unit_state(), "npc_bren_marr")
    combat.start(state, ["npc_bren_marr"], 0, "test")
    hidden = arm(state, "secret", "a concealed clockwork dagger", ["iron"], 0.3, "knife", length=0.25)
    hidden["hidden"] = {"by": "player"}
    seen = {}

    def read(context):
        seen.update(context)
        return voice.VoiceCall(status="fallback", text="", model="stub"), None

    monkeypatch.setattr(voice, "react", read)
    routes_minds._personal_reaction(state, {"npc_id": "npc_bren_marr", "kind": "decide", "why": "hurt badly"})
    assert "fight" in seen["_rules"] and "fighting" in seen["fight_now"]
    assert seen["what_just_happened"] == "hurt badly"
    assert "concealed clockwork dagger" not in seen["situation"]


def test_extinguishing_a_brand_removes_burn_damage_at_contact():
    state = open_ground(unit_state(), "npc_hessa_marr")
    brand = arm(state, "brand", "burning stick", ["wood"], 0.5, "brand", length=0.6)
    brand["burning"] = True
    combat.strike(state, "right", "npc_hessa_marr", 0)
    brand["burning"] = False
    assert gear.weapon(brand)["type"] == "blunt"
    beat(state, 320)
    assert not any(c["kind"] == "burn" for c in npc(state, "npc_hessa_marr").get("conditions", []))


def test_disarming_an_opponent_during_recovery_requests_a_new_individual_decision():
    state = open_ground(unit_state(), "npc_bren_marr")
    bren = npc(state, "npc_bren_marr")
    combat.start(state, [bren["id"]], 0, "test")
    beat(state, 400)
    bren = npc(state, bren["id"])
    blade = gear.weapon_in_hand(state, bren)
    blade["condition"] = "destroyed"
    beat(state, 1)
    assert any(p["npc_id"] == bren["id"] and "weapon" in p["why"] for p in state["pending_minds"])


def test_ammunition_lost_during_draw_does_not_materialize_a_shot():
    state = unit_state()
    arm(state, "bow", "bow", ["wood"], 0.6, "bow", length=1.2, flags=("flexible",))
    state["objects"]["arrows"] = {
        "id": "arrows",
        "name": "arrows",
        "holder_id": "player",
        "count": 2,
        "gear": {"kind": "ammo", "class": "arrow", "quality": "fair"},
    }
    state["player"]["equipped"]["ammo"] = "arrows"
    assert combat.strike(state, "right", None, 0)["ok"]
    state["objects"]["arrows"]["holder_id"] = "lost"
    beat(state, 900)
    assert not state.get("projectiles") and state["objects"]["arrows"]["count"] == 2


def test_repair_during_windup_does_not_restore_a_committed_blunted_edge():
    state = unit_state()
    blade = arm(state, "knife", "knife", ["iron"], 0.3, "knife", length=0.25, flags=("rigid", "sharp_edge"))
    effects.apply(
        state,
        [{"kind": "damage", "target_id": "knife", "name": "blunted", "flags": ["sharp_edge"]}],
        0,
        "player",
        lambda _obj: None,
    )
    swing = combat.strike(state, "right", None, 0)["swing"]
    assert swing["profile"]["type"] == "blunt"
    effects.apply(
        state, [{"kind": "repair", "target_id": "knife", "flags": ["sharp_edge"]}], 1, "player", lambda _obj: None
    )
    current = combat._current_profile(state, state["player"], swing, swing["profile"])
    assert current["type"] == "blunt" and current["damage"] == swing["profile"]["damage"]
    assert gear.weapon(blade)["type"] == "pierce"


def test_a_guard_does_not_transfer_to_a_different_shield_hand():
    state = open_ground(unit_state(), "npc_bren_marr")
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
    bren = npc(state, "npc_bren_marr")
    assert combat.guard(state, True, facing(state, bren["id"]), 0)["ok"]
    state["player"]["equipped"] = {"right": "shield"}
    assert not combat._can_block(state, state["player"], bren)


def test_a_broken_supporting_arm_prevents_two_handed_attacks_and_guarding():
    state = open_ground(unit_state(), "npc_bren_marr")
    arm(state, "sledge", "sledge", ["iron", "wood"], 6.0, "sledge", length=1.0, flags=("rigid",))
    state["player"]["conditions"] = [{"kind": "broken", "area": "arm", "treated": 0}]
    assert not combat.strike(state, "right", None, 0)["ok"]
    state["player"]["conditions"][0]["treated"] = 2
    assert combat.strike(state, "right", None, 1)["ok"]
    state["player"]["swings"] = {}
    state["player"]["equipped"] = {}
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
    assert combat.guard(state, True, facing(state, "npc_bren_marr"), 2)["ok"]
    state["player"]["conditions"][0]["treated"] = 0
    assert not combat._can_block(state, state["player"], npc(state, "npc_bren_marr"))


def test_a_reclassified_heavy_weapon_cannot_use_the_hand_still_holding_a_shield():
    state = unit_state()
    arm(state, "mace", "flanged mace", ["wood", "iron"], 7.9, "mace", length=0.8, flags=("rigid",))
    arm(state, "shield", "shield", ["wood"], 2, "round", kind="shield", hand="left")
    # Legacy saves can hold a formerly generic mace alongside a shield; its new class needs both hands.
    state["objects"]["mace"]["gear"] = {"kind": "none", "class": None, "quality": "fair"}
    assert not combat.strike(state, "right", None, 0)["ok"]
    assert gear.equip(state, state["player"], state["objects"]["mace"], "right")["ok"]
    assert combat.strike(state, "right", None, 1)["ok"]


def test_a_fighting_npc_springs_the_worlds_traps_and_obeys_the_new_limits():
    state = open_ground(unit_state(), "npc_bren_marr")
    bren = npc(state, "npc_bren_marr")
    bren.update(x=48, y=56)
    state["objects"]["snare"] = {
        "id": "snare",
        "name": "cord snare",
        "x": 48,
        "y": 57,
        "holder_id": None,
        "mass_kg": 0.5,
        "condition": "usable",
        "flags": [],
        "trap": {"by": "player", "name": "bound", "value": "caught in cord", "limits": ["move", "hands"], "minutes": 1},
    }
    combat.start(state, [bren["id"]], 0, "test")
    beat(state, 1000)
    caught = npc(state, bren["id"])
    assert cast.cell(caught) == (48, 57)
    assert effects.limited(caught, "move") and effects.limited(caught, "hands")
    assert state["objects"]["snare"]["trap"]["sprung"]
    assert bren["id"] not in state["fight"]["swings"]
    assert any(p["npc_id"] == bren["id"] and p["kind"] == "decide" for p in state["pending_minds"])
