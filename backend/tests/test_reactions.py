"""The moment itself (GDD D-39): code reacts in the same event as a crime, before any model is asked,
and the words are in the right person ("my bowl", "get off me")."""

from test_craft import attempt, judged  # noqa: F401
from test_encounter import post, world  # noqa: F401
from test_talk import npc, unit_state

import minds
from ai import decider


def test_a_theft_is_answered_at_once_in_the_victims_own_words(world, monkeypatch):
    asked = []
    monkeypatch.setattr(decider, "decide", lambda *a: asked.append(a) or decider.DeciderCall("x"))
    state = world.http.post("/runs", json={"mode": "developer"}).json()
    state = post(world, state, "move", {"cells": [[48, y] for y in range(67, 54, -1)]})["state"]
    state = post(world, state, "move", {"cells": [[x, 55] for x in range(47, 38, -1)]})["state"]
    state = post(world, state, "quick", {"verb": "take", "object_id": "bowl_hessa"})["state"]  # Walks there first.
    hessa = npc(state, "npc_hessa_marr")
    assert hessa["mind"]["said"]["text"] in (
        "Oi! That's my clay bowl!",
        "Hey! Put my clay bowl down!",
        "Thief! That's mine!",
    ), hessa["mind"]["said"]
    assert hessa["mind"]["facing_player"] and hessa["mind"]["feelings"]["anger"] >= 0.67
    assert {"npc_id": "npc_hessa_marr", "kind": "decide", "why": "victim"} in state["pending_minds"]
    assert not asked  # All of that by code: the decider decides what she does next, in the reaction lane.
    assert minds.worst_memory(hessa)["item"] == "clay bowl" and minds.worst_memory(hessa)["severity"] == 2


def test_lines_about_a_victim_are_first_person_when_they_are_the_victim():
    state = unit_state()
    hessa = npc(state, "npc_hessa_marr")
    minds.remember(
        hessa,
        {
            "kind": "violence",
            "severity": 2,
            "event": 3,
            "summary": "The stranger hit me.",
            "short": "attacked me",
            "victim": "npc_hessa_marr",
            "clarity": "clear",
            "source": "victim",
        },
    )
    words = minds.slots(state, hessa)
    assert words["relation"] == "me" and words["owners"] == "mine"
    lines = [o["line"] for o in minds._options(state, hessa).values() if o["line"]]
    assert not any("Hessa" in line for line in lines), lines
    situation = minds._situation(state, hessa)
    assert "trust" in situation and "fear 0.0" not in situation
