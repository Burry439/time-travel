"""The world's vocabulary (D-65): every deed the judge allows changes the world through general building blocks, each
with a law in code, a reducer and a consumer. From the user's own play: chalk writing on bark, water over Bren and a
kiss for Hessa were "done" and changed nothing; a kiss was seen by nobody."""

import typing

import pytest
from test_craft import attempt, commit, fresh_state, judged
from test_encounter import post, world  # noqa: F401

import briefing
import cast
import clock
import crafting
import effects
import judge_view
import npc_sim
import paths
import rounds
import tuning
from ai import judge

HESSA, BREN = "npc_hessa_marr", "npc_bren_marr"


def beside(npc_id, dx=1, dy=1):
    state = fresh_state()
    who = cast.find(state["npcs"], npc_id)
    state["player"].update(x=who["x"] + dx, y=who["y"] + dy)
    return state


def other(effects_list, seen_as="", **fields):
    return judged("other", effects=effects_list, seen_as=seen_as, **fields)


def test_every_block_has_a_law_a_reducer_and_a_consumer():
    assert set(typing.get_args(judge.EffectKind)) == set(effects.REGISTRY)
    for kind, block in effects.REGISTRY.items():
        assert block.family and block.noticed_by and block.check and block.apply, kind
        silent = block.apply is effects._no_change
        # Seen or heard, and nothing else: the people it reaches decide what it means (perception).
        assert not silent or kind in ("touch", "gesture", "sound", "visual_signal"), f"{kind} changes nothing"


def test_water_over_bren_soaks_him_and_he_remembers_it():
    state = beside(BREN)
    soaked = {"kind": "condition", "target_id": BREN, "name": "soaked", "value": "drenched head to foot", "minutes": 30}
    commit(state, other([soaked], "The stranger tips a pot of water over Bren's head."))
    bren = cast.find(state["npcs"], BREN)
    assert state["last_action"]["category"] == "success"
    assert bren["states"][0]["name"] == "soaked" and bren["states"][0]["until"]
    mine = [m for m in bren["mind"]["memories"] if m["kind"] == "deed"]
    assert mine and "water over Bren" in mine[-1]["summary"] and mine[-1]["source"] == "victim"
    assert any(p["npc_id"] == BREN for p in state["pending_minds"])  # He decides what it means, in his own call.
    assert "soaked: drenched head to foot" in briefing.world_as_seen(state, bren)["how_you_are"][0]


def test_a_state_ends_when_its_time_is_up():
    state = beside(BREN)
    commit(state, other([{"kind": "condition", "target_id": BREN, "name": "soaked", "minutes": 1}], "x"))
    assert effects.expire(state, state["sim_time_ms"] + 61_000) == [BREN]
    assert not cast.find(state["npcs"], BREN)["states"]


@pytest.mark.parametrize(
    "effect, problem",
    [
        ({"kind": "condition", "target_id": "npc_kade_east", "name": "soaked"}, "within reach"),
        ({"kind": "condition", "target_id": BREN, "name": "trust"}, "not something a deed can set"),
        ({"kind": "condition", "target_id": BREN, "name": "x", "limits": ["fly"]}, "limits only"),
        ({"kind": "touch", "target_id": "player"}, "someone else"),
        ({"kind": "touch", "target_id": "made_up_thing"}, "someone or something"),
        ({"kind": "write", "target_id": "made_up_bark", "text": "hello"}, "surface within reach"),
        ({"kind": "consume", "target_id": "gate_brackets"}, "something loose"),
        (
            {
                "kind": "attribute",
                "target_id": BREN,
                "attribute": {"name": "feelings", "value": "in love", "status": "expected", "basis_ids": ["player"]},
            },
            "not something",
        ),
    ],
)
def test_the_laws_refuse_what_the_world_cannot_do(effect, problem):
    state = beside(BREN)
    verdict = crafting.validate(state, other([effect], "x"))
    assert verdict["category"] == "unresolved"
    assert any(problem in n for n in verdict["notes"]), verdict["notes"]


def test_a_kiss_is_seen_and_the_one_kissed_decides_what_it_means():
    state = beside(HESSA)
    far = cast.find(state["npcs"], "npc_darin_ko")
    commit(state, other([{"kind": "touch", "target_id": HESSA}], "The stranger kisses Hessa on the lips."))
    hessa = cast.find(state["npcs"], HESSA)
    kiss = [m for m in hessa["mind"]["memories"] if m["kind"] == "deed"]
    assert kiss and kiss[-1]["source"] == "victim" and "kisses Hessa" in kiss[-1]["summary"]
    assert not any(m["kind"] == "deed" for m in (far.get("mind") or {}).get("memories", []))  # Out of sight.


def test_someone_blindfolded_sees_nothing():
    state = beside(BREN)
    oren = cast.find(state["npcs"], "npc_oren_dast")
    oren.update(x=state["player"]["x"] + 2, y=state["player"]["y"])
    oren["states"] = [{"name": "blindfolded", "value": "", "limits": ["see"], "since": 0, "until": None, "by": "x"}]
    commit(state, other([{"kind": "gesture"}], "The stranger makes a rude sign."))
    assert not any(m["kind"] == "deed" for m in (oren.get("mind") or {}).get("memories", []))


def test_bound_hands_and_feet_stop_the_stranger_and_hold_people_in_place():
    state = beside(BREN)
    state["player"]["states"] = [
        {"name": "tied up", "value": "", "limits": ["move", "hands"], "since": 0, "until": None, "by": BREN}
    ]
    verdict = crafting.validate(state, judged("take", take_ids=["branch_a"]))
    assert verdict["category"] == "blocked" and "tied up" in verdict["reason"]
    bren = cast.find(state["npcs"], BREN)
    bren["states"] = [{"name": "tied up", "value": "", "limits": ["move"], "since": 0, "until": None, "by": "player"}]
    where = (bren["x"], bren["y"])
    npcs, _, _ = clock.advance_world(state, 20_000, state["sim_time_ms"])
    assert (cast.find(npcs, BREN)["x"], cast.find(npcs, BREN)["y"]) == where


def test_writing_on_bark_is_there_for_anyone_close_to_read():
    state = fresh_state(52, 64)  # Beside the strip of bark.
    note = {"kind": "write", "target_id": "bark_a", "text": "Let the bearer through", "as_if_from": "Captain Roderic"}
    commit(state, other([note], "The stranger chalks words onto a strip of bark."))
    bark = state["objects"]["bark_a"]
    writing = next(a for a in bark["attributes"] if a["name"] == "writing")
    assert "Let the bearer through" in writing["value"] and "claims to be from Captain Roderic" in writing["value"]
    assert bark["revision"] == 1
    kade = cast.find(state["npcs"], "npc_kade_east")
    kade.update(x=53, y=64)
    seen = briefing.world_as_seen(state, kade)["what_you_can_see"]
    assert any("Let the bearer through" in line for line in seen)


def test_eating_someone_elses_food_uses_it_up_and_is_theirs():
    state = beside(HESSA)
    commit(state, other([{"kind": "consume", "target_id": "garlic_hessa"}], "The stranger eats Hessa's garlic."))
    assert state["objects"]["garlic_hessa"]["holder_id"] == "used"
    assert any(c["id"] == "garlic_hessa" and c["how"] == "used up" for c in state["last_action"]["property"])


def test_effects_ride_on_any_action_not_only_physical():
    state = fresh_state(47, 67)
    step = judged(
        "take",
        take_ids=["branch_a"],
        effects=[
            {
                "kind": "attribute",
                "target_id": "branch_a",
                "attribute": {
                    "name": "notch",
                    "value": "cut near one end",
                    "status": "observed",
                    "basis_ids": ["branch_a"],
                },
            }
        ],
    )
    commit(state, step)
    notch = next(a for a in state["objects"]["branch_a"]["attributes"] if a["name"] == "notch")
    assert notch["status"] == "expected"  # Only a real test asserts observed.


def test_words_typed_as_a_deed_go_to_talk(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    import commands

    with commands.open(state["run_id"], playable=False, stale=False) as cmd:
        hessa = cast.find(cmd.state["npcs"], HESSA)
        cmd.state["player"].update(x=hessa["x"] + 1, y=hessa["y"] + 1)
        cmd.save("test-position")
        state = cmd.state
    said = {"to_id": HESSA, "words": "What's up, Hessa?"}
    world.rulings.append(attempt(judged("other", say_instead=said)))
    reply = post(world, state, "encounter/act", {"kind": "do", "text": "ask hess awhats up", "target_id": HESSA})
    assert reply["round"]["entries"][0]["text"].startswith("You: “What's up, Hessa?”") or any(
        "What's up, Hessa?" in e.get("text", "") for e in reply["round"]["entries"]
    )
    assert rounds.said_instead(None) is None


def test_a_conscious_person_wont_stand_still_to_be_tied_up():
    """Live (D-65): an armed guard got his hands tied behind his back because he was facing away."""
    state = beside(BREN)
    tie = {"kind": "condition", "target_id": BREN, "name": "tied up", "limits": ["hands", "move"]}
    verdict = crafting.validate(state, other([tie], "x"))
    assert verdict["category"] == "unresolved" and any("won't stand still" in n for n in verdict["notes"])
    cast.find(state["npcs"], BREN)["down"] = True
    assert crafting.validate(state, other([tie], "x"))["category"] == "success"


def test_water_poured_over_someone_leaves_them_soaked_until_they_dry():
    state = beside(BREN)
    state["objects"]["gourd_a"].update(holder_id="player", water_l=1.0, capacity_l=1.5)
    pour = {
        "target_id": BREN,
        "weapon_id": "gourd_a",
        "method": "poured",
        "family": "pour",
        "outcome": "landed",
        "target_area": "head",
        "held_seconds": 0,
        "result": "wounded",
        "injury": "soaked",
    }
    commit(state, judged("harm", harm=pour))
    bren = cast.find(state["npcs"], BREN)
    assert bren["states"][0]["name"] == "soaked" and bren["states"][0]["until"]
    assert state["objects"]["gourd_a"]["water_l"] == 0.0


# --- Phase 2: place and structure, containers and mixtures, matter ---------------------------------------------------


def deed(state, *effects_list, seen_as="The stranger does something.", **fields):
    commit(state, other(list(effects_list), seen_as, **fields))
    return state["last_action"]


def refused(state, *effects_list, **fields):
    verdict = crafting.validate(state, other(list(effects_list), "x", **fields))
    assert verdict["category"] == "unresolved", verdict
    return " ".join(verdict["notes"])


def test_water_tipped_over_bren_leaves_the_gourd_and_soaks_him():
    """Phase 1 left the water in the gourd when a step soaked Bren with a condition: liquid is now conserved."""
    state = beside(BREN)
    state["objects"]["gourd_a"].update(holder_id="player", water_l=1.0)
    deed(state, {"kind": "transfer", "target_id": "gourd_a", "other_id": BREN, "relation": "over"})
    bren = cast.find(state["npcs"], BREN)
    assert bren["states"][0]["name"] == "soaked" and "water" in bren["states"][0]["value"]
    assert state["objects"]["gourd_a"]["water_l"] == 0.0 and state["water_spilled_l"] == 1.0


def test_poured_from_pot_to_pot_nothing_is_lost():
    state = fresh_state(34, 53)
    state["objects"]["bucket_hessa"]["water_l"] = 5.0
    deed(state, {"kind": "transfer", "target_id": "bucket_hessa", "other_id": "gourd_a", "amount": 0.4})
    assert state["objects"]["gourd_a"]["water_l"] == 0.4 and state["objects"]["bucket_hessa"]["water_l"] == 4.6
    deed(state, {"kind": "transfer", "target_id": "bucket_hessa", "other_id": "cup_hessa"})  # All: the cup overflows.
    assert state["objects"]["cup_hessa"]["water_l"] == 0.3 and state["water_spilled_l"] == 4.3


def test_honey_stirred_into_water_is_what_the_drinker_drank():
    state = fresh_state(34, 53)
    state["objects"]["bucket_hessa"]["water_l"] = 2.0
    mix = {"kind": "mix", "target_id": "bucket_hessa", "other_id": "honey_hessa", "amount": 0.2, "value": "sweet"}
    deed(state, mix)
    assert state["objects"]["honey_hessa"]["mass_kg"] == 0.4 and state["objects"]["honey_hessa"]["holder_id"] is None
    assert "pot of honey: sweet" in judge_view._placement(state, state["objects"]["bucket_hessa"])["mixed_in"]
    drink = {"kind": "transfer", "target_id": "bucket_hessa", "other_id": "player", "relation": "into", "amount": 0.5}
    deed(state, drink)
    drank = state["player"]["states"][0]
    assert drank["name"] == "drank" and "honey" in drank["value"] and state["objects"]["bucket_hessa"]["water_l"] == 1.5
    assert "bucket_hessa" in {c["id"] for c in state["last_action"]["property"]}  # Hessa's water, used.


def test_a_fouled_trough_fouls_what_is_filled_from_it_and_nobody_can_see_it():
    state = fresh_state(37, 53)
    deed(state, {"kind": "contaminate", "target_id": "trough_hessa", "value": "the stranger pissed in it"})
    assert state["objects"]["trough_hessa"]["mixture"][0]["name"] == "fouled"
    hessa = cast.find(state["npcs"], HESSA)
    assert not any("piss" in line for line in briefing.world_as_seen(state, hessa).get("what_you_can_see", []))
    view = {w["id"]: w for w in judge_view.water_sources(state, judge_view.walk_costs(state))}
    assert "pissed" in view["trough_hessa"]["mixed_in"]  # The judge knows the truth.
    state["objects"]["gourd_a"].update(holder_id="player")
    commit(state, judged("fill", fill={"container_id": "gourd_a", "source_id": "trough_hessa", "litres": 0.5}))
    assert state["objects"]["gourd_a"]["mixture"][0]["name"] == "fouled"


def test_a_log_rolled_across_a_way_blocks_it_until_it_is_moved():
    state = fresh_state(69, 60)
    deed(state, {"kind": "block", "target_id": "log_a", "cell": [70, 62]})
    log = state["objects"]["log_a"]
    assert (log["x"], log["y"]) == (70, 62) and log["blocks"]
    assert not paths.grid(state).walkable((70, 62)) and not paths.standing_grid(state).walkable((70, 62))
    deed(state, {"kind": "move", "target_id": "log_a", "cell": [68, 61]})
    assert not state["objects"]["log_a"]["blocks"] and paths.grid(state).walkable((70, 62))


def test_people_on_their_rounds_go_around_a_blocked_way():
    state = fresh_state()
    npc = cast.find(state["npcs"], HESSA)
    npc["controller"].update(activity="walk", source="routine", path=[[35, 51], [36, 51], [37, 51]], step_ms=100)
    state["objects"]["log_a"].update(x=35, y=51, blocks=True)
    moved = npc_sim.advance_npcs(state, [npc], 300, state["sim_time_ms"])
    hessa = cast.find(moved, HESSA)
    assert (hessa["x"], hessa["y"]) != (35, 51)
    assert (35, 51) not in {tuple(c) for c in hessa["controller"]["path"]}


def test_a_plank_on_a_stone_falls_when_the_stone_is_moved():
    state = fresh_state(65, 28)
    deed(state, {"kind": "place", "target_id": "wood_tomas", "other_id": "fulcrum_tomas", "relation": "on"})
    plank = state["objects"]["wood_tomas"]
    assert plank["rests_on"] == "fulcrum_tomas" and (plank["x"], plank["y"]) == (66, 27)
    deed(state, {"kind": "move", "target_id": "fulcrum_tomas", "cell": [67, 29]})
    assert plank["rests_on"] is None


def test_a_ladder_leans_against_the_nearest_wall():
    state = fresh_state(62, 28)
    deed(state, {"kind": "support", "target_id": "ladder_tomas"})
    ladder = state["objects"]["ladder_tomas"]
    assert ladder["rests_on"] == "wall" and (ladder["x"], ladder["y"]) == (62, 26)
    tomas = cast.find(state["npcs"], "npc_tomas_reed")
    assert any("propped against the wall" in line for line in briefing.world_as_seen(state, tomas)["what_you_can_see"])


def test_garlic_in_a_sealed_bucket_is_out_of_reach_until_the_seal_is_broken():
    state = fresh_state(34, 52)
    deed(state, {"kind": "put_in", "target_id": "garlic_hessa", "other_id": "bucket_hessa"})
    assert state["objects"]["garlic_hessa"]["inside"] == "bucket_hessa"
    deed(state, {"kind": "seal", "target_id": "bucket_hessa", "other_id": "thread_hessa", "value": "lid lashed shut"})
    bucket = state["objects"]["bucket_hessa"]
    assert bucket["sealed"] and state["objects"]["thread_hessa"]["holder_id"] == "in:bucket_hessa"
    assert "garlic_hessa" not in {o["id"] for o in judge_view.available_items(state)}
    assert "sealed" in refused(state, {"kind": "contaminate", "target_id": "bucket_hessa", "value": "dirt"})
    commit(state, judged("take", take_ids=["bucket_hessa"]))
    assert state["objects"]["garlic_hessa"]["holder_id"] == "player"  # It goes where the bucket goes.
    deed(state, {"kind": "open", "target_id": "bucket_hessa"})
    assert any(a["value"] == "the seal is broken" for a in bucket["attributes"])
    deed(state, {"kind": "take_out", "target_id": "garlic_hessa"})
    assert state["objects"]["garlic_hessa"].get("inside") is None
    assert any(c["id"] == "garlic_hessa" and c["how"] == "taken" for c in state["last_action"]["property"])


def test_writing_hidden_away_cannot_be_read():
    state = fresh_state(52, 64)
    deed(state, {"kind": "write", "target_id": "bark_a", "text": "Meet me at the well"})
    deed(state, {"kind": "hide", "target_id": "bark_a", "other_id": "clay_a", "value": "under the lump of clay"})
    kade = cast.find(state["npcs"], "npc_kade_east")
    kade.update(x=53, y=64)
    assert not briefing.world_as_seen(state, kade).get("what_you_can_see")
    assert "bark_a" in {o["id"] for o in judge_view.available_items(state)}  # The stranger knows where it is.
    commit(state, judged("take", take_ids=["bark_a"]))
    assert state["objects"]["bark_a"]["hidden"] is None


def test_a_holed_bucket_leaks_drops_what_it_held_and_can_be_mended():
    state = fresh_state(34, 52)
    state["objects"]["bucket_hessa"]["water_l"] = 4.0
    deed(state, {"kind": "put_in", "target_id": "garlic_hessa", "other_id": "bucket_hessa"})
    hole = {"kind": "damage", "target_id": "bucket_hessa", "name": "holed", "flags": ["container", "watertight"]}
    deed(state, hole)
    bucket = state["objects"]["bucket_hessa"]
    assert bucket["water_l"] == 0.0 and bucket["capacity_l"] == 0.0 and state["water_spilled_l"] == 4.0
    assert state["objects"]["garlic_hessa"].get("inside") is None
    assert any(c["id"] == "bucket_hessa" and c["how"] == "damaged" for c in state["last_action"]["property"])
    fill = judged("fill", fill={"container_id": "bucket_hessa", "source_id": "trough_hessa", "litres": 1})
    assert crafting.validate(state, fill)["category"] == "blocked"
    deed(state, {"kind": "repair", "target_id": "bucket_hessa", "other_id": "honey_hessa", "flags": []})
    assert {"container", "watertight"} <= set(bucket["flags"]) and bucket["capacity_l"] == 10.0
    assert not bucket["damage"]


def test_a_cup_smashed_is_gone_and_its_owner_lost_it():
    state = fresh_state(34, 52)
    shift = {"kind": "move", "target_id": "cup_hessa", "cell": [36, 54]}  # Moved, then smashed: smashed (live).
    deed(state, shift, {"kind": "destroy", "target_id": "cup_hessa", "value": "stamped flat"})
    assert state["objects"]["cup_hessa"]["condition"] == "destroyed"
    assert "cup_hessa" not in {o["id"] for o in judge_view.available_items(state)}
    assert any(c["id"] == "cup_hessa" and c["how"] == "destroyed" for c in state["last_action"]["property"])


def test_a_graver_claim_replaces_the_actions_own():
    """Live: a bowl smashed as physical work was recorded as only "used"."""
    state = fresh_state(34, 52)
    smash = {"kind": "destroy", "target_id": "bowl_hessa"}
    commit(state, judged("physical", effects=[smash], resource_ids=["bowl_hessa"], seen_as="x"))
    assert [c["how"] for c in state["last_action"]["property"] if c["id"] == "bowl_hessa"] == ["destroyed"]


def test_a_log_rolled_over_blocks_where_it_lies():
    """Live: the judge can't see where the path runs, so a block with no cell is where the thing lies."""
    state = fresh_state(69, 60)
    deed(state, {"kind": "block", "target_id": "log_a"}, {"kind": "open", "target_id": "log_a"})  # Open: no harm.
    assert state["objects"]["log_a"]["blocks"] and not paths.grid(state).walkable((70, 60))


@pytest.mark.parametrize(
    "at, effect, problem",
    [
        ((38, 66), {"kind": "move", "target_id": "sapling_a", "cell": [38, 64]}, "rooted"),
        ((37, 53), {"kind": "move", "target_id": "trough_hessa", "cell": [38, 54]}, "a thing within reach"),
        ((53, 13), {"kind": "move", "target_id": "gate_beam", "cell": [55, 15]}, "too heavy"),
        ((48, 10), {"kind": "destroy", "target_id": "gate_bar"}, "fitted in place"),
        ((48, 10), {"kind": "damage", "target_id": "gate_brackets", "name": "bent"}, "fitted in place"),
        ((44, 52), {"kind": "block", "target_id": "gourd_a", "cell": [44, 54]}, "bigger than"),
        ((62, 28), {"kind": "hide", "target_id": "ladder_tomas"}, "only small things"),
        ((34, 52), {"kind": "transfer", "target_id": "bucket_hessa", "other_id": "gourd_a"}, "empty"),
        ((34, 52), {"kind": "repair", "target_id": "cup_hessa", "flags": ["sharp_edge"]}, "isn't damaged"),
        ((34, 52), {"kind": "damage", "target_id": "cup_hessa", "name": "dull", "flags": ["sharp_edge"]}, "begin with"),
        ((34, 52), {"kind": "put_in", "target_id": "bucket_hessa", "other_id": "cup_hessa"}, "hasn't room"),
        ((34, 52), {"kind": "move", "target_id": "bucket_hessa"}, "where it goes"),
    ],
)
def test_the_phase_two_laws_refuse_what_the_world_cannot_do(at, effect, problem):
    state = fresh_state(*at)
    assert problem in refused(state, effect)


def test_drinking_more_than_a_body_holds_is_refused():
    state = beside(BREN)
    state["objects"]["bucket_hessa"].update(holder_id="player", water_l=6.0)
    drink = {"kind": "transfer", "target_id": "bucket_hessa", "other_id": BREN, "relation": "into", "amount": 5}
    assert "nobody drinks more" in refused(state, drink)


def test_honey_tipped_from_its_pot_goes_in_as_a_mix():
    """Live: the judge poured honey into the bucket with transfer; the pot holds no water, so it's a mix."""
    state = fresh_state(34, 53)
    state["objects"]["bucket_hessa"]["water_l"] = 2.0
    deed(
        state,
        {
            "kind": "transfer",
            "target_id": "honey_hessa",
            "other_id": "bucket_hessa",
            "relation": "into",
            "amount": 0.05,
        },
    )
    assert state["objects"]["bucket_hessa"]["mixture"][0]["name"] == "pot of honey"
    assert state["objects"]["honey_hessa"]["mass_kg"] == 0.55


def test_a_mix_named_the_other_way_round_still_goes_into_the_container():
    state = fresh_state(34, 53)
    state["objects"]["bucket_hessa"]["water_l"] = 2.0
    deed(state, {"kind": "mix", "target_id": "honey_hessa", "other_id": "bucket_hessa", "amount": 0.1})
    assert state["objects"]["bucket_hessa"]["mixture"][0]["name"] == "pot of honey"


def test_an_effect_on_the_thing_being_made_is_part_of_it():
    """Live (craft evals, judge_v23): a stake made with an attribute effect on made_by_step_1 was refused."""
    state = fresh_state(47, 67)
    for i in ("branch_a", "flint_a"):
        state["objects"][i]["holder_id"] = "player"
    point = {
        "name": "pointed end",
        "value": "shaved to a point",
        "status": "expected",
        "basis_ids": ["branch_a", "flint_a"],
    }
    spec = {
        "name": "stake",
        "description": "A sharpened branch.",
        "materials": ["wood"],
        "consumes": ["branch_a"],
        "tools_used": ["flint_a"],
        "mass_kg": 1.1,
        "length_m": 1.0,
        "capacity_l": None,
        "rated_load_kg": None,
        "flags": ["rigid"],
        "capabilities": [],
        "gear": None,
        "attributes": [],
    }
    step = judged(
        "make", new_object=spec, effects=[{"kind": "attribute", "target_id": "made_by_step_1", "attribute": point}]
    )
    verdict = crafting.validate(state, step)
    assert verdict["category"] == "success", verdict["notes"]
    assert verdict["new_spec"]["attributes"][0]["name"] == "pointed end"


def test_honey_stirred_into_a_full_bucket_slops_a_little_over():
    state = fresh_state(34, 53)
    state["objects"]["bucket_hessa"]["water_l"] = 10.0
    deed(state, {"kind": "mix", "target_id": "bucket_hessa", "other_id": "honey_hessa", "amount": 0.2})
    assert state["objects"]["bucket_hessa"]["water_l"] == 9.8 and state["water_spilled_l"] == 0.2


def test_water_consumed_is_drunk_not_used_up():
    """Live: "drink from the trough" came back as consume of the trough, refused as not loose."""
    state = fresh_state(37, 53)
    deed(state, {"kind": "consume", "target_id": "trough_hessa"})
    assert state["objects"]["trough_hessa"]["water_l"] == 79.7 and state["objects"]["trough_hessa"]["holder_id"] is None
    assert state["player"]["states"][0]["name"] == "drank"


# --- Phase 3: signals and terrain ------------------------------------------------------------------------------------

MARA = "npc_mara_venn"


def hidden_from(npc_id, near=12, far=20):
    """A fresh world with the stranger out of sight of someone (a building between), near..far cells away."""
    state = fresh_state()
    who = cast.find(state["npcs"], npc_id)
    grid = paths.grid(state)
    for x in range(who["x"] - far, who["x"] + far + 1):
        for y in range(who["y"] - far, who["y"] + far + 1):
            d = ((x - who["x"]) ** 2 + (y - who["y"]) ** 2) ** 0.5
            if near <= d <= far and grid.walkable((x, y)) and not paths.line_of_sight(state, (x, y), cast.cell(who)):
                state["player"].update(x=x, y=y)
                return state
    raise AssertionError("no hidden cell")


def heard(state, npc_id):
    return [
        m for m in (cast.find(state["npcs"], npc_id).get("mind") or {}).get("memories", []) if m["kind"] == "signal"
    ]


def test_a_shout_is_heard_through_walls_and_they_know_only_which_way_it_came_from():
    state = hidden_from(MARA)
    deed(state, {"kind": "sound", "value": "a long shout for help"})
    memory = heard(state, MARA)[-1]
    assert "shout for help" in memory["summary"] and "from the" in memory["summary"]
    assert memory["actor_id"] is None  # Not seen: not known to be the stranger.
    assert any(p["npc_id"] == MARA for p in state["pending_minds"])  # They decide what to do about it.
    assert not heard(state, "npc_roderic_vale")  # Too far off.


def test_a_gag_stops_a_shout_but_not_a_bell():
    state = beside(BREN)
    state["player"]["states"] = [
        {"name": "gagged", "value": "", "limits": ["speak"], "since": 0, "until": None, "by": BREN}
    ]
    assert "can't cry out" in refused(state, {"kind": "sound", "value": "help!"})
    state["objects"]["cup_hessa"].update(x=state["player"]["x"], y=state["player"]["y"], flags=["rigid", "sound_loud"])
    deed(state, {"kind": "sound", "value": "a clanging", "other_id": "cup_hessa"})
    assert heard(state, "npc_roderic_vale")


def test_a_mirror_flash_is_seen_far_off_but_only_in_a_line_of_sight():
    state = fresh_state(81, 32)  # Beside Darin's polished mirror.
    deed(state, {"kind": "visual_signal", "value": "a bright flash of sunlight", "other_id": "mirror_darin"})
    seen = {n["id"] for n in state["npcs"] if heard(state, n["id"])}
    for npc in state["npcs"]:
        far = cast.distance(npc, state["player"])
        sight = paths.line_of_sight(state, cast.cell(npc), (81, 32))
        assert (npc["id"] in seen) == (far <= tuning.FAR_SIGNAL_CELLS and sight), npc["id"]


def test_in_disguise_a_deed_is_pinned_on_someone_else_except_by_those_who_know_your_face():
    state = beside(HESSA)
    state["objects"]["cloth_darin"].update(holder_id="player")
    deed(state, {"kind": "disguise", "other_id": "cloth_darin", "value": "wrapped in a linen hood"})
    assert effects.disguise_of(state["player"]) == "wrapped in a linen hood"
    cast.mind(cast.find(state["npcs"], HESSA))["met"] = True
    deed(state, {"kind": "touch", "target_id": HESSA}, seen_as="The stranger pinches Hessa's cheek.")
    hessa = cast.find(state["npcs"], HESSA)
    assert [m for m in hessa["mind"]["memories"] if m["kind"] == "deed"][-1]["summary"].startswith("The stranger")
    unmet = cast.find(state["npcs"], "npc_darin_ko")
    unmet.update(x=state["player"]["x"] + 4, y=state["player"]["y"])
    commit(state, other([{"kind": "gesture"}], "The stranger makes a rude sign."))
    rude = [m for m in unmet["mind"]["memories"] if m["kind"] == "deed"][-1]
    assert rude["summary"].startswith("Someone wrapped in a linen hood") and rude["actor_id"] == effects.DISGUISED
    assert any(
        "Someone wrapped in a linen hood" in line for line in briefing.world_as_seen(state, unmet)["what_you_can_see"]
    )


def test_a_pit_dug_with_a_stick_is_in_the_way_until_it_is_filled_in():
    state = fresh_state(48, 68)
    assert "something stout" in refused(state, {"kind": "dig", "amount": 1.0})  # Bare hands only scrape.
    state["objects"]["branch_a"]["holder_id"] = "player"
    deed(state, {"kind": "dig", "name": "pit", "amount": 1.0, "cell": [49, 68]})  # The branch in hand (live).
    pit = next(o for o in state["objects"].values() if o.get("feature") == "pit")
    assert (pit["x"], pit["y"]) == (49, 68) and pit["blocks"] and pit["sprite_asset_id"]
    assert not paths.grid(state).walkable((49, 68))
    deed(state, {"kind": "fill_in", "target_id": pit["id"]})
    assert paths.grid(state).walkable((49, 68)) and pit["condition"] == "filled in"


def test_a_plank_bridges_a_pit_and_a_barrier_closes_a_way():
    state = fresh_state(64, 29)
    state["objects"]["branch_a"].update(holder_id="player")
    deed(state, {"kind": "dig", "amount": 1.0, "other_id": "branch_a", "cell": [65, 30]})
    pit = next(o for o in state["objects"].values() if o.get("feature") == "pit")
    assert "rigid at least" in refused(
        state, {"kind": "build", "name": "bridge", "ids": ["rope_tomas"], "structure": "bridge", "other_id": pit["id"]}
    )
    deed(
        state,
        {"kind": "build", "name": "plank bridge", "ids": ["wood_tomas"], "structure": "bridge", "other_id": pit["id"]},
    )
    assert paths.grid(state).walkable((65, 30)) and state["objects"]["wood_tomas"]["holder_id"].startswith("in:")
    assert "more than" in refused(
        state, {"kind": "build", "name": "fence", "ids": ["rope_tomas"], "structure": "barrier"}
    )
    deed(
        state,
        {
            "kind": "build",
            "name": "barricade",
            "ids": ["ladder_tomas", "fulcrum_tomas"],
            "structure": "barrier",
            "cell": [63, 29],
        },
    )
    assert not paths.grid(state).walkable((63, 29))
    assert any(c["id"] == "ladder_tomas" and c["how"] == "used up" for c in state["last_action"]["property"])


def test_a_covered_pit_catches_someone_walking_their_round_but_not_whoever_dug_it():
    state = fresh_state(36, 53)
    state["objects"]["branch_a"].update(holder_id="player")
    state["objects"]["leaves_a"].update(holder_id="player")
    deed(state, {"kind": "dig", "amount": 1.0, "other_id": "branch_a", "cell": [37, 51]})
    pit = next(o for o in state["objects"].values() if o.get("feature") == "pit")
    deed(
        state,
        {
            "kind": "trap",
            "name": "fallen into a pit",
            "ids": ["leaves_a"],
            "target_id": pit["id"],
            "value": "drops them into the pit",
        },
    )
    assert pit["hidden"] and not pit["blocks"] and paths.grid(state).walkable((37, 51))
    hessa = cast.find(state["npcs"], HESSA)
    assert all("covered" not in line for line in briefing.world_as_seen(state, hessa).get("what_you_can_see", []))
    assert effects.spring(state, state["player"], (37, 51), 0) is None  # The one who set it knows where it is.
    hessa["controller"].update(
        activity="walk", source="routine", path=[[35, 51], [36, 51], [37, 51], [38, 51]], step_ms=100
    )
    moved = cast.find(npc_sim.advance_npcs(state, [hessa], 500, state["sim_time_ms"]), HESSA)
    assert (moved["x"], moved["y"]) == (37, 51) and moved["states"][0]["name"] == "fallen into a pit"
    assert "move" in moved["states"][0]["limits"] and moved["mind"]["memories"][-1]["kind"] == "trap"
    assert pit["trap"]["sprung"] and pit["blocks"] and not pit["hidden"]


@pytest.mark.parametrize(
    "at, effect, problem",
    [
        ((48, 68), {"kind": "dig", "amount": 3, "other_id": "branch_a"}, "depth up to"),
        ((48, 68), {"kind": "trap", "name": "snare", "ids": ["stone_a"]}, "cord, rope or vine"),
        ((48, 68), {"kind": "visual_signal", "value": "x", "other_id": "mirror_darin"}, "within reach"),
        ((48, 68), {"kind": "disguise", "value": "as a guard", "other_id": "mail_bren"}, "to disguise them with"),
        ((48, 68), {"kind": "fill_in", "target_id": "stone_a"}, "a pit or trench"),
    ],
)
def test_the_phase_three_laws_refuse_what_the_world_cannot_do(at, effect, problem):
    state = fresh_state(*at)
    state["objects"]["branch_a"]["holder_id"] = "player"
    assert problem in refused(state, effect)


def test_a_thing_placed_with_nothing_named_goes_on_the_ground_where_you_stand():
    """Live: a cord loop "set low across the ground" came back as place with no other_id."""
    state = fresh_state(49, 67)
    state["objects"]["cord_a"]["holder_id"] = "player"
    deed(state, {"kind": "place", "target_id": "cord_a", "relation": "on"})
    cord = state["objects"]["cord_a"]
    assert cord["holder_id"] is None and (cord["x"], cord["y"]) == (49, 67)
