"""What went wrong in the player's own journeys on 7 Oct 2026 (D-72), each kept as a test: the pot that couldn't sit on
Hessa's fire, a 0.4 L fill refused for an iron bar in the pack, Hessa's words replaced by a stock line when her deal
move was refused, a yes in words that gave no permission, people walking up uninvited, and a device that advised
the fire the judge would refuse."""

from test_craft import fresh_state, judged
from test_scenes import moment
from test_talk import said

import agreements
import cast
import crafting
import device
import encounter
import rounds
import village

HESSA = "npc_hessa_marr"


def near_hessas_yard():
    state = fresh_state(37, 53)  # Between the trough (36, 52) and the cooking fire (38, 52).
    for heavy in ("yard_iron_pot", "yard_iron_bar_2", "yard_iron_plates"):
        state["objects"][heavy].update(holder_id="player", x=37, y=53)
    return state


def test_a_pot_can_be_set_on_the_cooking_fire():
    state = near_hessas_yard()
    on_fire = {"kind": "place", "target_id": "yard_iron_pot", "other_id": "cookfire_hessa", "relation": "on"}
    verdict = crafting.validate(state, judged("other", effects=[on_fire], resource_ids=["yard_iron_pot"]))
    assert verdict["category"] == "success", verdict["reason"]


def test_a_full_pack_never_stops_a_fill_or_a_pick_up():
    state = near_hessas_yard()
    for oid in ("yard_hammerstone", "yard_iron_wire", "yard_river_stones", "yard_steel_billet"):
        if oid in state["objects"]:
            state["objects"][oid].update(holder_id="player")
    fill = {"container_id": "yard_iron_pot", "source_id": "trough_hessa", "litres": 4.0}
    verdict = crafting.validate(state, judged("fill", fill=fill, resource_ids=["yard_iron_pot", "trough_hessa"]))
    assert verdict["category"] == "success", verdict["reason"]
    took = crafting.validate(state, judged("take", take_ids=["trough_boards"], resource_ids=["trough_boards"]))
    assert took["category"] == "success", took["reason"]


def test_one_thing_too_heavy_for_one_person_still_needs_help():
    state = fresh_state()
    log = state["objects"]["log_a"]  # 28 kg.
    state["player"].update(x=log["x"], y=log["y"] + 1)
    verdict = crafting.validate(state, judged("take", take_ids=["log_a"], resource_ids=["log_a"]))
    assert verdict["category"] == "blocked" and "can't be picked up" in verdict["reason"], verdict["reason"]


def test_doing_what_was_asked_completes_a_deal_nobody_formally_accepted():
    state = fresh_state()
    hessa = cast.find(state["npcs"], HESSA)
    vouch = {"goal": [], "kind": "vouch", "object_ids": [], "task": "Speak to Captain Roderic for the stranger."}
    ok, deal_id = agreements.apply(
        state, hessa, {"action": "offer", "task": "Find what fouls the trough.", "rewards": [vouch]}, 1
    )
    assert ok and state["agreements"][deal_id]["status"] == "proposed"
    ok, detail = agreements.apply(state, hessa, {"action": "satisfied", "agreement_id": deal_id}, 2)
    assert ok and state["agreements"][deal_id]["status"] == "fulfilled", detail
    ok, detail = agreements.apply(state, hessa, {"action": "satisfied", "agreement_id": deal_id}, 3)
    assert not ok and detail == "That deal is already fulfilled; it can't be satisfied now."  # Says which, not why not.


def talking_with_hessa():
    state = near_hessas_yard()
    encounter.open_for_talk(state, cast.find(state["npcs"], HESSA), state["sim_time_ms"])
    return state


def test_a_refused_move_never_replaces_what_they_said():
    state = talking_with_hessa()
    words = "Good. You found it. I'll put in a word for you."
    reply = {**said("answer"), "text": words, "agreement": {"action": "satisfied", "agreement_id": "no_such_deal"}}
    scene, _ = moment(state, HESSA, [(HESSA, reply)], "It was the boards: something dead under them.")
    spoken = rounds.apply_scene(state, scene, "It was the boards.", None, state["sim_time_ms"])
    assert (
        spoken[0]["line"] == words
    )  # Her words stand (once they were "I can't carry that out with what I have here").
    assert spoken[0]["unmet"] and spoken[0]["unmet"][0].startswith("Hessa's deal doesn't change")
    record = {"round": 1, "entries": [], "walked_away": False, "cues_before": {}}
    encounter.finish(
        state, record, state["sim_time_ms"], [{k: v for k, v in s.items() if k != "trace"} for s in spoken]
    )
    kinds = [(e["kind"], e["text"]) for e in record["entries"]]
    assert kinds[0] == ("reply", f"Hessa: “{words}”") and kinds[1] == ("cue", spoken[0]["unmet"][0])


def test_a_yes_in_words_to_using_their_thing_is_a_lend():
    state = talking_with_hessa()
    reply = {**said("answer"), "text": "Aye, love, you may. Lift them clear."}
    scene, _ = moment(state, HESSA, [(HESSA, reply)], "Can I move the rotten boards?")
    scene["call"].lines[0]["lets_use"] = "trough_boards"
    spoken = rounds.apply_scene(state, scene, "Can I move the rotten boards?", None, state["sim_time_ms"])
    assert spoken[0]["key"] == "lend:trough_boards"


def test_someone_who_wants_a_word_waits_to_be_spoken_to():
    state = fresh_state()
    hessa = cast.find(state["npcs"], HESSA)
    cast.mind(hessa)["said"] = {"key": "k", "text": "Have you found what's fouling my trough?", "at": 1000}
    village.apply_agenda(state, hessa, {"agenda": {"choice": "stranger"}}, 1500)
    assert not cast.mind(hessa)["job"]  # She doesn't walk up to the stranger.
    assert cast.mind(hessa)["wants_word"]["text"] == "Have you found what's fouling my trough?"
    encounter.open_for_talk(state, hessa, 2000)  # The stranger goes to her: her request is answered.
    assert "wants_word" not in cast.mind(hessa)


def test_the_device_knows_the_worlds_own_facts_about_fire():
    state = fresh_state()
    facts = device.context(state, "how do I start a fire")["how_things_work_here"]
    assert "steel" in facts["fire"] and "no spark" in facts["iron"]
