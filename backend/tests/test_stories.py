"""The village's storylines in the main game (D-56, parked; D-61, brought back). Stories have goals and no methods:
code checks each stage and outcome as a result in the world. People confide secrets and agree to story moves only
when code says they could and they choose to, each in their own call; what the stranger passes on about others is
a reading beside the conversation, so no one's call holds anyone else's secrets."""

import json
from types import SimpleNamespace

from test_craft import commit, fresh_state, judged
from test_talk import npc, said, unit_state

import briefing
import cast
import clock
import content
import conversation
import gear
import minds
import paths
import persona
import reputation
import rounds
import stories
import talk
import tuning
import views
from ai import config, voice


def learn(state, **entry):
    """Something the stranger was told (a lead in their journal)."""
    state.setdefault("learned", []).append({"npc_id": "npc_hessa_marr", "lead": "…", **entry})


def test_the_village_runs_every_story_and_a_training_level_none():
    state = unit_state()
    assert {s["id"] for s in stories.running(state)} == set(stories.STORIES)
    assert stories.page(state) == [] and not stories.pending(state)
    level = next(i for i, level in content.LEVELS.items() if level.get("steps"))
    assert stories.running({**state, "scenario": level}) == [] and stories.page({**state, "scenario": level}) is None


def test_a_secret_is_its_owners_to_confide_when_they_choose_to():
    state = unit_state()
    bren = npc(state, "npc_bren_marr")
    assert any(k.startswith("confide:") for k in conversation.replies(state, bren))  # His to weigh (D-62).
    reputation.regard(bren)["trust"] = 0.55
    options = conversation.replies(state, bren)
    assert "confide:bren_covers_oren" in options and "confide:bren_elin" in options  # Bren weighs each secret himself.
    context = briefing.scene_context(state, bren, [bren], [], "You look tired. Long night?", None)
    assert "confide" in context["people"][0]["_rules"]  # The rules for it, in his own call only.
    payload = talk.exchange(
        state, "npc_bren_marr", "You look tired.", said("x"), "confide:bren_covers_oren", "Keep this quiet.", []
    )
    assert payload["learned"][0]["secret"] == "bren_covers_oren"
    assert "Oren" in payload["learned"][0]["lead"]
    state.setdefault("learned", []).extend(payload["learned"])
    assert "confide:bren_covers_oren" not in conversation.replies(state, bren)  # Told once.
    assert stories.pending(state) and stories.tick(state)
    assert state["stories"]["stages"] == {"oren_debt": ["brens_risk"]} and state["journal"][-1]["kind"] == "story"
    assert stories.page(state)[0]["title"] == "Dice and Debts" and stories.page(state)[0]["ended"] is None
    assert stories.page(state)[0]["steps"][0]["from"] == "Bren"  # Whose side it came from (D-70).


def test_someone_who_knows_of_a_crime_by_the_stranger_confides_nothing():
    state = unit_state()
    bren = npc(state, "npc_bren_marr")
    reputation.regard(bren)["trust"] = 0.9
    cast.mind(bren)["memories"].append(
        {
            "kind": "violence",
            "victim": "npc_bren_marr",
            "item": None,
            "clarity": "clear",
            "source": "victim",
            "at": 0,
            "event": 1,
            "summary": "The stranger attacked Bren.",
            "short": "attacked me",
            "severity": 3,
        }
    )
    assert stories.confidable(state, bren)  # A grudge informs their decision, not a universal veto.


def test_a_story_move_is_theirs_to_make_and_settles_the_story():
    state = unit_state()
    darin, oren = npc(state, "npc_darin_ko"), npc(state, "npc_oren_dast")
    assert "story:forgive_oren_debt" not in conversation.replies(state, darin)
    learn(state, fact="oren_debt")
    reputation.regard(darin)["trust"] = 0.6
    assert "story:forgive_oren_debt" in conversation.replies(state, darin)
    assert "story" in briefing.scene_context(state, darin, [darin], [], "Let Oren off.", None)["people"][0]["_rules"]
    trust_before = reputation.regard(oren)["trust"]
    warmth_before = persona.opinions(oren).get("npc_darin_ko", {}).get("warmth", 0.0)
    payload = talk.exchange(
        state, "npc_darin_ko", "Let Oren's debt go.", said("x"), "story:forgive_oren_debt", "Fine. It's forgotten.", []
    )
    assert payload["learned"][0]["story"] == "forgive_oren_debt" and state["stories"]["moves"] == ["forgive_oren_debt"]
    assert stories.tick(state) and state["stories"]["outcomes"] == {"oren_debt": "cleared_quietly"}
    assert reputation.regard(oren)["trust"] == trust_before
    assert persona.opinions(oren)["npc_darin_ko"]["warmth"] == warmth_before
    assert "story:forgive_oren_debt" not in conversation.replies(state, darin)  # Settled.
    assert not stories.how_things_stand(state, oren)  # He has not yet been told.
    assert views.lead_done(state, payload["learned"][0])
    # Darin goes and tells him (the move's "tells", D-63); Oren's reaction comes with the news, once.
    job = cast.mind(darin)["job"]
    assert job["kind"] == "tell" and job["target"] == "npc_oren_dast" and job["event"] == state["event_seq"] + 1
    clock._deliver_message(state, darin, oren, 5000, [], job)
    assert stories.pending(state) and stories.tick(state)
    assert reputation.regard(oren)["trust"] == round(trust_before + 0.4, 3)
    assert persona.opinions(oren)["npc_darin_ko"]["warmth"] == round(warmth_before + 0.3, 2)
    assert any("Oren's debt" in line and "the stranger" in line for line in stories.how_things_stand(state, oren))
    assert not stories.pending(state) and not stories.tick(state)  # Delivered once.


def test_what_the_stranger_tells_someone_is_theirs_to_know_and_stories_react():
    state = unit_state()
    roderic, tomas, bren = (npc(state, i) for i in ("npc_roderic_vale", "npc_tomas_reed", "npc_bren_marr"))
    learn(state, secret="tomas_cracked", npc_id="npc_tomas_reed")
    assert [s["id"] for s in stories.tellable(state, [roderic])] == ["tomas_cracked"]
    assert stories.tellable(state, [tomas]) == []  # His own: there's nothing to tell him.
    told = stories.tell(state, ["tomas_cracked", "oren_debt"], [roderic, tomas], 7, 1000)
    assert told == [{"secret": "tomas_cracked", "to": "npc_roderic_vale", "to_name": "Roderic", "about": "Tomas"}]
    assert stories.tellable(state, [roderic]) == []  # Heard once.
    trust_before = reputation.regard(tomas)["trust"]
    assert stories.tick(state) and state["stories"]["outcomes"] == {"gate_beam": "told_roderic"}
    assert reputation.regard(tomas)["trust"] == trust_before
    heard = briefing.converse_context(state, roderic, "Hello.", {})["the_stranger_told_you"]
    assert any("cracked" in line for line in heard)
    assert "the_stranger_told_you" not in briefing.converse_context(state, bren, "Hello.", {})
    state["objects"]["gate_beam"]["installed_in"] = "gate"  # The beam goes up afterwards:
    stories.tick(state)
    assert "raised" in state["stories"]["stages"]["gate_beam"]  # Repair remains possible after disclosure.
    assert "kept_quiet" not in state["stories"]["milestones"]["gate_beam"]
    # Tomas learns of it only when it reaches him (D-63): here, someone tells him what the captain was told.
    reputation.remember(
        tomas,
        {
            "kind": "disclosure",
            "event": 7,
            "object_id": "tomas_cracked",
            "victim": "npc_roderic_vale",
            "at": 2000,
            "severity": 1,
            "clarity": "told",
            "source": "told_by:npc_bren_marr",
            "summary": "…",
            "short": "…",
        },
    )
    assert stories.tick(state)
    assert reputation.regard(tomas)["trust"] == round(max(0.0, trust_before - 0.4), 3)
    assert any("captain" in line for line in stories.how_things_stand(state, tomas))


def test_nobody_learns_an_outcome_by_standing_near_or_having_once_seen_something():
    """Before D-63 anyone within sight who had ever seen any gift counted as knowing any outcome. Now: in sight but
    out of earshot, Kade doesn't hear the captain told; once someone tells him, he knows."""
    state = unit_state()
    kade, roderic = npc(state, "npc_kade_east"), npc(state, "npc_roderic_vale")
    state["player"].update(x=roderic["x"], y=roderic["y"] + 1)
    kade.update(x=roderic["x"], y=roderic["y"] + 1 + tuning.HEAR_TALK_CELLS + 3)  # Within sight, out of earshot.
    reputation.remember(
        kade,
        {
            "kind": "gift",
            "event": 2,
            "object_id": "rope_x",
            "object_ids": ["rope_x"],
            "victim": "npc_kade_east",
            "at": 0,
            "severity": 1,
            "clarity": "clear",
            "source": "received",
            "summary": "…",
            "short": "…",
        },
    )
    learn(state, secret="kade_knees", npc_id="npc_kade_east")
    trust_before = reputation.regard(kade)["trust"]
    stories.tell(state, ["kade_knees"], [roderic], 9, 1000)
    assert stories.tick(state) and "told_roderic" in state["stories"]["milestones"]["kade_knees"]
    told = {"kind": "told", "npc": "npc_roderic_vale", "secrets": ["kade_knees"]}
    knew = stories.knowers(state, told)  # The captain, and the guards beside him who overheard it.
    assert "npc_roderic_vale" in knew and "npc_kade_east" not in knew
    assert reputation.regard(kade)["trust"] == trust_before and not stories.how_things_stand(state, kade)
    clock._deliver_message(state, roderic, kade, 3000, [], {"message": "I hear about your knees.", "event": 9})
    assert "npc_kade_east" in stories.knowers(state, told) and stories.tick(state)
    assert reputation.regard(kade)["trust"] == round(max(0.0, trust_before - 0.5), 3)


def test_the_passing_on_is_read_beside_the_conversation_never_in_anyones_own_call(monkeypatch):
    state = unit_state()
    roderic, bren = npc(state, "npc_roderic_vale"), npc(state, "npc_bren_marr")
    learn(state, secret="oren_debt", npc_id="npc_oren_dast")
    calls = []

    class Client:
        responses = None

        def parse(self, **kwargs):
            calls.append(kwargs)
            if kwargs["text_format"] is voice.Told:
                return SimpleNamespace(usage=None, output_parsed=voice.Told(passed_on=["oren_debt", "made_up"]))
            payload = json.loads(kwargs["input"][1]["content"])
            line = voice.PersonLine(
                speaks=payload["your_part"] == "addressed",
                text="Is that so.",
                brought_up_story_beat=False,
                move="answer",
                impression="Unchanged",
                suspicion="Unchanged",
                anger="Calm",
                believes_what_was_said=True,
                sees_the_stranger_as_a_threat=False,
                reason_enough_to_let_them_through=False,
                agreed_to_the_deal=False,
                did_what_was_asked=False,
                feelings_toward_others=[],
                errand_to="",
                errand_message="",
                promised_later="",
                remember="",
                lets_the_stranger_use="",
                stranger_name="",
            )
            return SimpleNamespace(usage=None, output_parsed=line)

    client = Client()
    client.responses = client
    monkeypatch.setattr(config, "mode", lambda: "live")
    monkeypatch.setattr(config, "client", lambda: client)
    state["player"].update(x=roderic["x"], y=roderic["y"] + 1)
    bren.update(x=roderic["x"] + 1, y=roderic["y"] + 1)
    import encounter

    encounter.open_for_talk(state, roderic, state["sim_time_ms"])
    words = "Oren owes Darin eleven silver from dice."
    moment = rounds.scene(state, "npc_roderic_vale", words, None, True, nearby=[bren])
    assert moment["told"] == ["oren_debt"]  # Only what was offered comes back.
    people_calls = [c for c in calls if c["text_format"] is voice.PersonLine]
    assert people_calls and all(
        "eleven silver from dice, and Darin" not in c["input"][1]["content"] for c in people_calls
    )
    said_lines = rounds.apply_scene(state, moment, words, None, state["sim_time_ms"])
    assert stories.heard(roderic) == ["oren_debt"] and stories.heard(bren) == ["oren_debt"]  # Both heard it.
    assert state["journal"][-1]["kind"] == "told" and said_lines[0]["trace"]["passed_on"]
    stories.tick(state)
    assert state["stories"]["outcomes"]["oren_debt"] == "exposed"


def test_kade_s_knees_ache_from_the_start_and_a_poultice_eases_them():
    state = unit_state()
    kade = npc(state, "npc_kade_east")
    assert gear.describe(kade["conditions"][0]) == "the aching knees"
    assert not gear.untreated(kade)  # An old complaint: it doesn't drain him or stop him mending.
    poultice = {"id": "p1", "name": "willow poultice", "gear": {"kind": "remedy", "class": "poultice", "covers": []}}
    assert gear.treat(kade, 0, poultice, 1000)["ok"]
    assert stories.tick(state) and state["stories"]["outcomes"]["kade_knees"] == "eased"
    assert state["stories"]["stages"]["kade_knees"] == ["eased"]
    assert "confide:kade_knees" in conversation.replies(state, kade)  # Someone who noticed and was kind.


def test_a_gift_counts_as_given_by_the_stranger():
    mara = (18, 25)
    state = fresh_state(mara[0] + 1, mara[1])
    state["objects"]["iron_bar"] = {
        **state["objects"]["branch_a"],
        "id": "iron_bar",
        "name": "iron bar",
        "materials": ["iron"],
        "holder_id": "player",
        "owner_id": "player",
        "flags": ["rigid"],
        "gear": None,
    }
    commit(state, judged("give", give={"item_ids": ["iron_bar"], "recipient_id": "npc_mara_venn"}))
    assert state["objects"]["iron_bar"]["given_by"] == "player"
    assert stories.tick(state) and state["stories"]["outcomes"]["forge_iron"] == "found_iron"


def test_a_demonstration_remembers_what_was_shown_so_a_story_can_ask_what_it_was():
    state = unit_state()
    elin = npc(state, "npc_elin_west")
    state["objects"]["needle"] = {
        **state["objects"]["branch_a"],
        "id": "needle",
        "name": "floating needle",
        "materials": ["iron"],
        "flags": ["magnetized", "indicates_direction"],
        "holder_id": "player",
        "owner_id": "player",
    }
    cast.mind(elin)["memories"].append(
        {
            "kind": "demonstration",
            "victim": None,
            "item": "floating needle",
            "clarity": "clear",
            "works": True,
            "object_id": "needle",
            "source": "shown",
            "at": 0,
            "event": 1,
            "summary": "…",
            "short": "…",
            "severity": 1,
        }
    )
    assert stories.tick(state) and state["stories"]["stages"]["fog"] == ["heading", "proven"]


def test_an_errand_across_the_village_arrives():
    """Live (D-63): Darin, sent from his stall to pay Hessa at the inn, stood still for good: a step was only looked
    for within 60 steps, and the inn is farther by the village's paths."""
    state = unit_state()
    darin, hessa = npc(state, "npc_darin_ko"), npc(state, "npc_hessa_marr")
    darin.update(x=80, y=30)
    grid = paths.grid(state)
    assert paths.next_step((80, 30), (hessa["x"], hessa["y"]), 1.5, grid) is not None


def test_carrying_on_with_an_errand_keeps_it_and_says_so():
    """Live (D-63): a reconsideration right after Darin agreed sent him back to his stall ("carry on")."""
    state = unit_state()
    darin = npc(state, "npc_darin_ko")
    job = {"kind": "tell", "target": "npc_hessa_marr", "speed": "walk", "message": "Here's what I owe you.", "event": 4}
    cast.set_job(darin, job, 0)
    assert persona.doing(darin) == "on their way to tell Hessa: Here's what I owe you."
    minds.apply_decision(state, darin, {"action": {"choice": "carry_on"}}, 1000, [])
    assert cast.mind(darin)["job"]["kind"] == "tell"


def test_a_secret_about_someone_is_no_news_to_them():
    """Live (D-63): telling Darin that Hessa has carried his rent counted as passing on her confidence to him, and
    he turned on the stranger for it. It's his own rent: he knows."""
    state = unit_state()
    darin, roderic = npc(state, "npc_darin_ko"), npc(state, "npc_roderic_vale")
    learn(state, secret="hessa_darin_lodging", npc_id="npc_hessa_marr")
    assert stories.tellable(state, [darin]) == []
    assert stories.tell(state, ["hessa_darin_lodging"], [darin], 5, 0) == []
    assert [s["id"] for s in stories.tellable(state, [roderic])] == ["hessa_darin_lodging"]


def test_every_secret_names_real_people_who_already_know_it():
    for secret_id, (whose, secret) in stories.all_secrets().items():
        for person in secret.get("known_by", []):
            assert person in cast.CARDS and person != whose, (secret_id, person)


def test_hessa_decides_about_clean_water_once_she_knows_her_guests_are_sick():
    """Live (D-63): the move needed a demonstration that visibly worked, and nobody can see what boiling kills."""
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    assert "story:trust_clean_water" not in conversation.replies(state, hessa)
    learn(state, fact="sick_guests")
    assert "story:trust_clean_water" in conversation.replies(state, hessa)


def test_a_second_errand_waits_for_the_first():
    """Live (D-63): Darin agreed to let Oren's debt go, then to pay Hessa; the second errand replaced the first and
    Oren never heard."""
    state = unit_state()
    darin = npc(state, "npc_darin_ko")
    first = {"kind": "tell", "target": "npc_oren_dast", "speed": "walk", "message": "Your debt's gone.", "event": 3}
    second = {"kind": "tell", "target": "npc_hessa_marr", "speed": "walk", "message": "Here's the rent.", "event": 4}
    cast.add_errand(darin, first, 0)
    cast.add_errand(darin, second, 0)
    assert cast.mind(darin)["job"]["target"] == "npc_oren_dast"
    oren = npc(state, "npc_oren_dast")
    clock._arrived(state, state["npcs"], darin, cast.mind(darin)["job"], 1000, [])
    assert any(m["kind"] == "told" and m["event"] == 3 for m in cast.mind(oren)["memories"])
    assert cast.mind(darin)["job"]["target"] == "npc_hessa_marr"


def test_a_story_reads_a_property_held_as_an_attribute():
    """The quest play-through (D-63): the judge now records "magnetized" as an extensible attribute (D-62), so the fog
    story, looking only at flags, could never see the stranger's compass."""
    state = unit_state()
    state["objects"]["nail_a"]["attributes"] = [
        {"name": "magnetized", "value": "weakly", "status": "expected", "basis_ids": ["nail_a"]}
    ]
    state["objects"]["nail_a"].update(
        given_by="player",
        holder_id="npc_roderic_vale",
        owner_id="npc_roderic_vale",
        known_capabilities=[{"text": "points north", "status": "observed"}],
    )
    assert stories.tick(state) and "in_the_watchs_hands" in state["stories"]["milestones"]["fog"]
