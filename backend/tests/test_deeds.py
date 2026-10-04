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
import rounds
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
        assert not silent or kind in ("touch", "gesture"), f"{kind} changes nothing in the world"


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
