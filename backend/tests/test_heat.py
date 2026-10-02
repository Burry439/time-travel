"""Things that change (GDD D-40): water, heat and fire are judged like any attempt; code keeps only the laws
(heat and flame need something burning within reach, fire needs real sparks into tinder, water is conserved,
cold water can't scald) and time cools things and burns fires down. Names follow the state."""

from test_craft import commit, judged
from test_talk import npc, unit_state

import heat
import judge_view


def beside(state, x, y):
    state["player"].update(x=x, y=y)
    return state


def change(target, **fields):
    return {
        "target_id": target,
        "temperature": None,
        "burning": None,
        "heat_source_id": None,
        "pour_into_id": None,
        "pour_litres": None,
        **fields,
    }


def bowl_of_water(state):
    state["objects"]["bowl_hessa"].update(holder_id="player", owner_id="player")
    commit(state, judged("fill", fill={"container_id": "bowl_hessa", "source_id": "trough_hessa", "litres": 1.0}))
    return state["objects"]["bowl_hessa"]


def test_water_boils_only_over_real_heat_and_the_name_follows():
    state = beside(unit_state(), 37, 53)  # By the inn's cooking fire and trough.
    bowl = bowl_of_water(state)
    assert bowl["name"] == "clay bowl of water"
    summary = commit(
        state, judged("change", change=change("bowl_hessa", temperature="boiling", heat_source_id="cookfire_hessa"))
    )
    assert summary["category"] == "success" and bowl["name"] == "clay bowl of boiling water"
    assert bowl["temperature"] == "boiling" and bowl["water_l"] == 1.0
    cold = beside(unit_state(), 48, 66)  # Out on the road: nothing burning anywhere near.
    cold["objects"]["bowl_hessa"].update(holder_id="player", owner_id="player", water_l=1.0)
    summary = commit(
        cold, judged("change", change=change("bowl_hessa", temperature="boiling", heat_source_id="cookfire_hessa"))
    )
    assert summary["category"] == "blocked" and cold["objects"]["bowl_hessa"].get("temperature", "cold") == "cold"


def test_hot_things_cool_back_over_time():
    state = beside(unit_state(), 37, 53)
    bowl = bowl_of_water(state)
    commit(state, judged("change", change=change("bowl_hessa", temperature="boiling", heat_source_id="cookfire_hessa")))
    start = bowl["heated_at"]
    names = []
    for minutes in (1, 3, 8, 20, 40):
        fields = heat.age_objects(state, 0, start + minutes * 60_000).get("bowl_hessa", {})
        names.append(fields.get("name", bowl["name"]))
    assert names == [
        "clay bowl of boiling water",
        "clay bowl of hot water",
        "clay bowl of warm water",
        "clay bowl of water",
        "clay bowl of water",
    ]


def test_fire_needs_real_sparks_and_burns_down():
    state = beside(unit_state(), 45, 66)
    for item in ("flint_a", "grass_a", "branch_a"):
        state["objects"][item]["holder_id"] = "player"
    campfire = {
        "name": "small campfire",
        "description": "Dry grass and a branch, burning.",
        "materials": ["wood", "grass"],
        "consumes": ["grass_a", "branch_a"],
        "tools_used": ["flint_a"],
        "mass_kg": 1.0,
        "length_m": None,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["heat_source", "light_source", "combustible"],
        "capabilities": [{"text": "gives heat", "status": "expected"}],
    }
    commit(state, judged("make", new_object=dict(campfire)))  # Flint, but no iron to strike it on.
    made = state["objects"][f"made_{state['event_seq']}"]
    assert "heat_source" not in made["flags"] and not made.get("burning")
    state = beside(unit_state(), 45, 66)
    state["objects"]["horseshoe_a"].update(x=45, y=66)
    for item in ("flint_a", "grass_a", "branch_a", "horseshoe_a"):
        state["objects"][item]["holder_id"] = "player"
    commit(state, judged("make", new_object={**campfire, "tools_used": ["flint_a", "horseshoe_a"]}))
    fire = state["objects"][f"made_{state['event_seq']}"]
    assert fire["burning"] and "heat_source" in fire["flags"] and fire["holder_id"] is None
    later = heat.age_objects(state, 0, fire["burns_until"] + 1)[fire["id"]]
    assert later["burning"] is False and "heat_source" not in later["flags"]


def test_cold_water_only_soaks_and_boiling_water_scalds():
    state = beside(unit_state(), 37, 53)
    bowl_of_water(state)
    kade = npc(state, "npc_hessa_marr")
    state["player"].update(x=kade["x"], y=kade["y"] + 1)
    harm = {
        "target_id": "npc_hessa_marr",
        "weapon_id": "bowl_hessa",
        "method": "poured",
        "result": "wounded",
        "injury": "scalded face",
    }
    summary = commit(state, judged("harm", harm=dict(harm)))
    assert summary["harm"]["result"] == "missed" and "soaks" in summary["reason"]
    assert state["objects"]["bowl_hessa"]["water_l"] == 0 and state["objects"]["bowl_hessa"]["name"] == "clay bowl"


def test_a_fire_put_out_is_out_and_a_hand_in_a_burning_one_is_burnt():
    """The user's play (2 Oct 2026): a doused fire still read "flames licking" and still looked lit, and putting a
    hand into it was refused as "out of reach" from beside it. Put out, a fire reads and looks out, and is warm for
    a while; the stranger may put their hand into anything, walking over to it, and a burning fire burns it (D-59)."""
    state = beside(unit_state(), 45, 66)
    state["objects"]["horseshoe_a"].update(x=45, y=66)
    for item in ("flint_a", "grass_a", "branch_a", "horseshoe_a"):
        state["objects"][item]["holder_id"] = "player"
    campfire = {
        "name": "small fire",
        "description": "A small fire of grass and a branch, with flames licking above it.",
        "materials": ["wood", "grass"],
        "consumes": ["grass_a", "branch_a"],
        "tools_used": ["flint_a", "horseshoe_a"],
        "mass_kg": 1.0,
        "length_m": None,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["heat_source", "light_source", "combustible"],
        "capabilities": [],
    }
    commit(state, judged("make", new_object=campfire))
    fire = state["objects"][f"made_{state['event_seq']}"]
    hand = {"condition": "burn", "area": "arm", "severity": "minor", "cause_id": fire["id"]}
    beside(state, fire["x"], fire["y"] + 3)  # Three steps off: they walk over first.
    commit(state, judged("other", hurts_you=hand))
    assert [c["kind"] for c in state["player"]["conditions"]] == ["burn"] and state["player"]["health"] == 92
    assert abs(state["player"]["y"] - fire["y"]) <= 2
    commit(state, judged("change", change=change(fire["id"], burning=False)))
    assert fire["condition"] == "put out" and "flames" not in fire["description"] and fire["temperature"] == "warm"
    assert fire["id"] in {o["id"] for o in judge_view.available_items(state)}  # Still there to touch.
    commit(state, judged("other", hurts_you=hand))  # Out: warm, and it burns nobody.
    assert len(state["player"]["conditions"]) == 1 and state["player"]["health"] == 92
