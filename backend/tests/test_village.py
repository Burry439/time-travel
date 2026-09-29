"""The village's own life (GDD D-37): agendas the decider chooses among options built by code, the gate never
left short of guards, meetings that pass news and hearsay and shift opinions, chatter voiced only where
the stranger can see it, a decider budget, and replay of all of it."""
import copy

import crafting
import minds
import npc_sim
import persona
import village
from ai import config as ai_config
from ai import decider
from test_encounter import post, world  # noqa: F401
from test_talk import npc, unit_state


def choice(key, value):
    return {key: {"type": "choice", "choice": value, "confidence": 1.0, "probabilities": {value: 1.0}}}


def test_every_place_is_walkable_and_every_task_has_a_place():
    blocked = crafting._blocked_cells({"objects": {}})
    assert not [p for p, v in village.PLACES.items() if tuple(v["cell"]) in blocked]
    state = unit_state()
    for person in state["npcs"]:
        for task in minds.card(person)["tasks"]:
            assert task["place"] in village.PLACES, (person["id"], task["id"])


def test_the_world_changes_what_people_choose_to_do():
    state = unit_state()
    tomas = npc(state, "npc_tomas_reed")
    options = village.agenda_options(state, tomas)
    assert "task:measure_beam" in options and "task:celebrate" not in options
    assert {"carry_on", "task:bench", "rest"} <= set(options) and any(k.startswith("visit:") for k in options)
    state["objects"]["gate_beam"]["installed_in"] = "gate_brackets"
    options = village.agenda_options(state, tomas)
    assert "task:celebrate" in options and "task:measure_beam" not in options


def test_the_gate_is_never_left_short_of_guards():
    state = unit_state()
    bren, oren = npc(state, "npc_bren_marr"), npc(state, "npc_oren_dast")
    assert any(k.startswith("visit:") for k in village.agenda_options(state, bren))  # Roderic and Oren cover.
    oren["x"], oren["y"] = 64, 26  # Oren has wandered off to the carpenter's yard.
    oren["controller"]["destination"] = [64, 26]
    at_the_gate = {f"task:{t['id']}" for t in minds.card(bren)["tasks"] if village.PLACES[t["place"]].get("gate")}
    assert set(village.agenda_options(state, bren)) <= {"carry_on"} | at_the_gate  # He stays at his post.


def test_a_chosen_task_is_walked_to_done_and_left_for_the_routine():
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    record = village.apply_agenda(state, hessa, {**choice("agenda", "task:sweep"), **choice("mood", "weary")}, 0)
    assert record["doing"] == "sweeping the side of the yard" and persona.mood(hessa) == "weary"
    controller = hessa["controller"]
    assert controller["source"] == "agenda" and controller["path"][-1] == village.PLACES["inn_side"]["cell"]
    npcs = state["npcs"]
    for step in range(60):
        npcs = npc_sim.advance_npcs(npcs, 500, step * 500, crafting.m2._GEOMETRY)
    hessa = next(n for n in npcs if n["id"] == "npc_hessa_marr")
    assert [hessa["x"], hessa["y"]] == village.PLACES["inn_side"]["cell"] and hessa["controller"]["activity"] == "work"
    for step in range(60, 200):
        npcs = npc_sim.advance_npcs(npcs, 500, step * 500, crafting.m2._GEOMETRY)
    assert next(n for n in npcs if n["id"] == "npc_hessa_marr")["controller"]["source"] == "routine"


def test_the_decider_is_asked_only_when_something_happens_and_neighbours_fall_into_talk():
    state = unit_state()
    for t in range(0, 600_000, 30_000):  # Ten quiet minutes, the stranger out of sight: nobody asks the decider anything.
        village.schedule(state, state["npcs"], t)
    assert not [p for p in state["pending_minds"] if p["kind"] == "agenda"]
    hessa = npc(state, "npc_hessa_marr")
    minds.remember(hessa, {"kind": "theft", "severity": 2, "event": 7, "summary": "The stranger stole my bucket.",
                           "short": "stole my bucket", "victim": "npc_hessa_marr", "clarity": "clear", "source": "victim"})
    village.schedule(state, state["npcs"], 700_000)
    assert {"npc_id": "npc_hessa_marr", "kind": "agenda", "why": "stole my bucket"} in state["pending_minds"]
    state["player"].update(x=npc(state, "npc_mara_venn")["x"] + 2, y=npc(state, "npc_mara_venn")["y"])
    village.schedule(state, state["npcs"], 710_000)  # The stranger walks into view: that's news too.
    assert any(p["npc_id"] == "npc_mara_venn" and p["why"] == "the stranger came into view" for p in state["pending_minds"])
    state["pending_minds"] = []
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    bren["x"], bren["y"] = hessa["x"] + 1, hessa["y"]
    bren["controller"]["activity"] = hessa["controller"]["activity"] = "look"
    village.schedule(state, state["npcs"], 1_000_000)
    assert {"npc_id": "npc_bren_marr", "kind": "meet", "why": "npc_hessa_marr"} in state["pending_minds"]


def test_news_and_hearsay_travel_and_opinions_shift():
    state = unit_state()
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    minds.remember(hessa, {"kind": "theft", "severity": 2, "event": 7, "summary": "The stranger stole my bucket.",
                           "short": "stole a bucket", "victim": "npc_hessa_marr", "item": "bucket_hessa",
                           "clarity": "clear", "source": "victim"})
    persona.knows(hessa).update(name="Ash", episodes=[{"at": 0, "text": "Ash asked for work and seemed honest."}])
    options = village.topics(state, hessa, bren)
    assert {"news:7", "stranger", "worry", "small_talk"} <= set(options)
    warm = persona.opinions(bren)["npc_hessa_marr"]["warmth"]
    record = village.apply_meeting(state, hessa, bren, {**choice("topic", "news:7"),
                                                        "reaction": {"score": 4}, "believes": {"noul": 0.9}}, None, 100)
    assert record["topic"] == "news:7" and minds.knows(bren, 7)
    assert bren["mind"]["memories"][-1]["source"] == "told_by:npc_hessa_marr"
    assert {"npc_id": "npc_bren_marr", "kind": "decide", "why": "told by Hessa"} in state["pending_minds"]
    assert persona.opinions(bren)["npc_hessa_marr"]["warmth"] > warm
    village.apply_meeting(state, hessa, bren, {**choice("topic", "stranger"), "believes": {"noul": 0.9}}, None, 200)
    assert persona.knows(bren)["heard_name"] == "Ash" and persona.knows(bren)["heard"][-1]["from"] == "npc_hessa_marr"
    assert any("Heard from Hessa" in line for line in persona.stranger_lines(state, bren))


def test_chatter_is_voiced_only_where_the_stranger_can_see_it():
    state = unit_state()
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    state["player"].update(x=hessa["x"] + 30, y=hessa["y"])
    assert not village.chatter_allowed(state, hessa, 0)
    state["player"].update(x=hessa["x"] + 2, y=hessa["y"] + 1)
    assert village.chatter_allowed(state, hessa, 0)
    record = village.apply_meeting(state, hessa, bren, choice("topic", "small_talk"), ("Long day.", "Aye."), 0)
    assert minds.mind(hessa)["said"]["text"] == "Long day." and minds.mind(bren)["said"]["after_ms"] > 0
    assert [entry["said"] for entry in record["learned"]] == ["Long day.", "Aye."]  # Overheard: in the journal.
    village.apply_meeting(state, hessa, bren, choice("topic", "small_talk"), ("Again.", "Aye."), 10)
    assert not village.chatter_allowed(state, hessa, 20)  # At most two voiced chats a minute.


def test_the_village_thinks_in_the_lane_and_replays_and_keeps_to_budget(world, monkeypatch):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    for _ in range(40):  # Walking up the road brings people into view: they reconsider their day.
        if any(p["kind"] == "agenda" for p in state.get("pending_minds", [])):
            break
        y = state["player"]["y"] - 2
        state = post(world, state, "move", {"cells": [[48, y + 1], [48, y]]})["state"]
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]  # Time passes on the clock lane.
    assert any(p["kind"] == "agenda" for p in state.get("pending_minds", []))
    body = post(world, state, "think", {})
    state = body["state"]
    assert any(d["kind"] == "agenda" and d.get("agenda") == "carry_on" for d in body["decisions"])  # No answer: routine.
    assert world.http.get(f"/runs/{state['run_id']}").json() == state
    # Past the decider allowance, nobody asks the decider about their day: they carry on by routine.
    asked = []
    monkeypatch.setattr(ai_config, "max_decider_calls_per_run", lambda: 0)
    monkeypatch.setattr(decider, "decide", lambda text, questions: asked.append(questions) or decider.DeciderCall("x"))
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    for _ in range(40):
        if any(p["kind"] == "agenda" for p in state.get("pending_minds", [])):
            break
        y = state["player"]["y"] - 2
        state = post(world, state, "move", {"cells": [[48, y + 1], [48, y]]})["state"]
        state = post(world, state, "explore", {"elapsed_ms": 1000})["state"]  # Time passes on the clock lane.
    body = post(world, state, "think", {})
    assert not asked and any(d["kind"] == "agenda" for d in body["decisions"])


def test_the_dead_do_not_keep_the_village_thinking(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    import store
    with store.lock, store.db() as connection:
        _, current = store.load_run(connection, state["run_id"])
    working = copy.deepcopy(current)
    working["pending_minds"] = [{"npc_id": "npc_jory_venn", "kind": "agenda", "why": "test"}]
    minds.find(working["npcs"], "npc_jory_venn")["alive"] = False
    import routes_minds
    batch, recollecting, stale = routes_minds._choose(working)
    assert batch == [] and recollecting == []


def test_news_comes_first_when_they_would_tell_it_and_nothing_is_said_twice():
    state = unit_state()
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    minds.remember(hessa, {"kind": "theft", "severity": 2, "event": 7, "summary": "The stranger stole my bucket.",
                           "short": "stole a bucket", "victim": "npc_hessa_marr", "item": "bucket_hessa",
                           "clarity": "clear", "source": "victim"})
    _, questions = village.meet_brief(state, hessa, bren)
    assert "tells" in questions and "stole my bucket" in questions["tells"]["instructions"]
    record = village.apply_meeting(state, hessa, bren, {**choice("topic", "worry"), "tells": {"noul": 0.8}}, None, 0)
    assert record["topic"] == "news:7"  # She'd tell her brother about the theft before her own worries.
    first = village.apply_meeting(state, hessa, bren, choice("topic", "worry"), None, 1)["about"]
    second = village.apply_meeting(state, hessa, bren, choice("topic", "worry"), None, 2)["about"]
    assert first != second  # A different worry, not the same one again.


def test_a_wronged_person_can_tell_someone_or_have_it_out_and_errands_are_not_repeated():
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    minds.remember(hessa, {"kind": "theft", "severity": 2, "event": 7, "summary": "The stranger stole my bucket.",
                           "short": "stole a bucket", "victim": "npc_hessa_marr", "item": "bucket_hessa",
                           "clarity": "clear", "source": "victim"})
    options = village.agenda_options(state, hessa)
    tells = [k for k in options if k.startswith("tell:")]
    assert tells[0] == "tell:npc_bren_marr" and "her brother Bren" in options[tells[0]]["description"]  # Family first.
    assert "confront" in options
    record = village.apply_agenda(state, hessa, choice("agenda", "confront"), 0)
    assert hessa["mind"]["job"]["then"] == "confront" and record["agenda"] == "confront"
    minds._set_job(hessa, None, 1)
    assert "confront" not in village.agenda_options(state, hessa)  # Not straight back again.


def test_meetings_go_both_ways():
    state = unit_state()
    hessa, bren = npc(state, "npc_hessa_marr"), npc(state, "npc_bren_marr")
    minds.remember(hessa, {"kind": "theft", "severity": 2, "event": 7, "summary": "The stranger stole my bucket.",
                           "short": "stole a bucket", "victim": "npc_hessa_marr", "item": "bucket_hessa",
                           "clarity": "clear", "source": "victim"})
    _, questions = village.meet_brief(state, bren, hessa)  # Bren came over; Hessa has the news.
    assert "tells_back" in questions
    record = village.apply_meeting(state, bren, hessa, {**choice("topic", "small_talk"), "tells_back": {"noul": 0.9}},
                                   None, 0)
    assert record["told_back"] and minds.knows(bren, 7)
    assert {"npc_id": "npc_bren_marr", "kind": "decide", "why": "told by Hessa"} in state["pending_minds"]
