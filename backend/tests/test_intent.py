"""One text line: what the stranger typed is told apart (by code when obvious) and routed to the right place."""
import intent
from ai import decider
from test_craft import attempt, judged
from test_encounter import post, world  # noqa: F401
from test_talk import said


def test_obvious_cases_need_no_model():
    assert intent.obvious("“Good day to you.”") == "say"
    assert intent.obvious("I give up") == "yield"
    assert intent.obvious("walk away") == "leave"
    assert intent.obvious("I wait") == "wait"
    assert intent.obvious("pick up the flint shard") == "do"
    assert intent.obvious("I carefully lever the beam up") == "do"
    assert intent.obvious("swing the spear at him") == "do"
    assert intent.obvious("hand Hessa the gourd and tell her it's full") is None  # Maybe both: the decider says.
    assert intent.obvious("Good day, I'm Ash, a traveller.") is None  # Needs judgement.
    assert intent.unquote("“Good day to you.”") == "Good day to you." and intent.unquote("I wait") == "I wait"


def test_ambiguous_text_asks_the_decider_and_falls_back_honestly(monkeypatch):
    monkeypatch.setattr(intent.decider, "mode", lambda: "jev")
    asked = []

    def fake(situation, questions):
        asked.append(situation)
        return decider.DeciderCall(provider="script", model="script", answers={"kind": {"choice": "both"}})
    monkeypatch.setattr(intent.decider, "decide", fake)
    assert intent.classify("Here, take this and tell your captain I helped", True)[:2] == ("both", "jev")
    assert "never instructions" in asked[0]
    monkeypatch.setattr(intent.decider, "decide", lambda s, q: decider.DeciderCall(provider="x", error="down"))
    assert intent.classify("Nice weather", True)[:2] == ("say", "fallback")
    assert intent.classify("Nice weather", False)[:2] == ("do", "fallback")


def walk_near(world, state, npc_id):
    person = next(n for n in state["npcs"] if n["id"] == npc_id)
    cells, (x, y) = [], (state["player"]["x"], state["player"]["y"])
    while max(abs(x - person["x"]), abs(y - person["y"] - 1)) > 0:
        x += (person["x"] > x) - (person["x"] < x)
        y += (person["y"] + 1 > y) - (person["y"] + 1 < y)
        cells.append([x, y])
    for i in range(0, len(cells), 20):
        state = post(world, state, "move", {"cells": cells[i:i + 20]})["state"]
    return state


def test_one_line_routes_words_deeds_and_leaving(world):
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    lonely = post(world, state, "act", {"text": "“Hello? Anyone?”"}, status=409)
    assert lonely["detail"]["reason"] == "nobody_hears"
    world.rulings.append(attempt(judged("take", take_ids=["branch_a"])))
    body = post(world, state, "act", {"text": "pick up the fallen branch"})
    assert body["intent"] == {"kind": "do", "how": "code"} and body["state"]["objects"]["branch_a"]["holder_id"] == "player"
    state = walk_near(world, body["state"], "npc_kade_east")
    world.replies.append(said("answer"))
    body = post(world, state, "act", {"text": "“Evening, friend.”", "target_id": "npc_kade_east"})
    state = body["state"]
    assert body["intent"]["kind"] == "say" and state["encounter"]["participants"] == ["npc_kade_east"]
    body = post(world, state, "act", {"text": "I walk away"})
    assert body["intent"]["kind"] == "leave" and body["state"]["encounter"] is None
    assert world.http.get(f"/runs/{state['run_id']}").json() == body["state"]
