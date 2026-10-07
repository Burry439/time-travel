"""A deal and a quest step are one record of a favour (D-73). A person can make a deal for one of their quest needs;
when the quest step that answers that need reaches them, the deal is fulfilled and its rewards happen, whether or not
anyone says "done". What changes hands waits for the stranger to come to them."""

from test_craft import fresh_state

import agreements
import briefing
import cast
import encounter
import stories

HESSA = "npc_hessa_marr"
VOUCH = {"goal": [], "kind": "vouch", "object_ids": [], "task": "Speak to Captain Roderic for the stranger."}


def hessa_offers(state, rewards, for_quest="The Wayside Inn"):
    hessa = cast.find(state["npcs"], HESSA)
    stories.start(state)  # Her need: why her guests fell sick from the trough.
    offer = {"action": "offer", "task": "Find out what is fouling the trough.", "rewards": rewards}
    ok, deal_id = agreements.apply(state, hessa, {**offer, "for_quest": for_quest}, 1)
    assert ok
    return hessa, state["agreements"][deal_id]


def answer_her_need(state):
    """The "clean" step reaching her: its effect replaces her need with the next one."""
    story = stories.STORIES["trough_water"]
    clean = next(s for s in story["stages"] if s["id"] == "clean")
    for effect in clean["effects"]:
        if effect["kind"] == "need":
            stories.EFFECTS["need"](state, effect, story)


def test_a_deal_names_the_quest_need_it_is_for():
    state = fresh_state()
    title = stories.STORIES["trough_water"]["title"]
    _, deal = hessa_offers(state, [VOUCH], for_quest=title)
    assert deal["for_need"]["story"] == "trough_water" and deal["for_need"]["title"] == title
    assert "it settles itself" in " ".join(briefing.open_deals(state, cast.find(state["npcs"], HESSA)))
    _, other = hessa_offers(fresh_state(), [VOUCH], for_quest="Something else entirely")
    assert "for_need" not in other  # Not one of her needs: an ordinary deal, judged by her.


def test_the_quest_step_that_answers_her_need_keeps_her_word():
    state = fresh_state()
    title = stories.STORIES["trough_water"]["title"]
    hessa, deal = hessa_offers(state, [VOUCH], for_quest=title)
    answer_her_need(state)
    assert deal["status"] == "fulfilled" and deal["settled_by"] == "quest"
    assert cast.mind(hessa)["job"]["kind"] == "vouch"  # She sets off to speak for the stranger.
    kept = [e for e in state["journal"] if e.get("category") == "deal_kept"]
    assert kept and kept[-1]["npc_id"] == HESSA and "keeps their word" in kept[-1]["reason"]
    answer_her_need(state)  # Answered again: nothing more happens.
    assert len([e for e in state["journal"] if e.get("category") == "deal_kept"]) == 1


def test_what_changes_hands_waits_for_the_stranger_to_come_to_them():
    state = fresh_state()  # The stranger is far down the south road.
    title = stories.STORIES["trough_water"]["title"]
    cup = {"goal": [], "kind": "give", "object_ids": ["cup_hessa"], "task": "Give the stranger a cup."}
    hessa, deal = hessa_offers(state, [cup], for_quest=title)
    answer_her_need(state)
    assert deal["status"] == "fulfilled" and deal["owed"] and state["objects"]["cup_hessa"]["holder_id"] != "player"
    assert cast.mind(hessa)["wants_word"]["text"] == "Come and see me: I've what I promised you."
    state["player"].update(x=hessa["x"], y=hessa["y"] + 1)  # The stranger comes to her.
    encounter.open_for_talk(state, hessa, state["sim_time_ms"])
    assert state["objects"]["cup_hessa"]["holder_id"] == "player" and not deal.get("owed")


def test_a_deal_she_already_judged_done_is_not_paid_twice():
    state = fresh_state()
    title = stories.STORIES["trough_water"]["title"]
    hessa, deal = hessa_offers(state, [VOUCH], for_quest=title)
    assert agreements.apply(state, hessa, {"action": "satisfied", "agreement_id": deal["id"]}, 2)[0]
    cast.set_job(hessa, None, 0)  # Her errand for it is over.
    answer_her_need(state)
    assert not cast.mind(hessa)["job"] and "settled_by" not in deal
