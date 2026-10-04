"""One character sheet per person, read by the decider and the voice alike (GDD D-38).

Personality used to be split: the decider never saw how someone talks or what persuades them, and the voice
never saw their goals or the people they know. Everything here comes from the authored card plus
what has happened to them: their mood, what they're doing, how they feel about the people around
them, and what they remember of the stranger (D-36). Free text from models only ever lands in
memory (notes, episodes); it never changes world state.
"""

from __future__ import annotations

import math

import cast
import content
import npc_sim
import tuning
from shapes import Npc, State

MOODS = ["content", "cheerful", "weary", "irritable", "anxious", "excited", "grieving"]
NOTES_KEPT = 12  # Notes from the current conversation.
EPISODES_KEPT = 6  # Past conversations kept as short summaries; older ones merge into long_memory.
NEARBY_CELLS = 16


def knows(npc: Npc) -> dict:
    """What this person has gathered about the stranger over every conversation (and from others)."""
    return cast.mind(npc).setdefault(
        "knows",
        {
            "name": None,
            "notes": [],
            "claims": [],
            "episodes": [],
            "long_memory": "",
            "heard": [],
            "since": 0,
            "talks": 0,
        },
    )


def mood(npc: Npc) -> str:
    return cast.mind(npc).get("mood") or cast.card(npc).get("mood") or "content"


def opinions(npc: Npc) -> dict:
    """How they feel about the people they know; starts from the card, shifts as people talk (D-37)."""
    my_mind = cast.mind(npc)
    if "opinions" not in my_mind:
        my_mind["opinions"] = {k: dict(v) for k, v in cast.card(npc).get("opinions", {}).items()}
    return my_mind["opinions"]


def warmth_words(warmth: float) -> str:
    return (
        "dislikes"
        if warmth <= -0.4
        else "is wary of"
        if warmth < 0
        else "is neutral about"
        if warmth < 0.2
        else "likes"
        if warmth < 0.6
        else "is fond of"
    )


def doing(npc: Npc) -> str:
    return cast.mind(npc).get("doing") or (npc.get("controller") or {}).get("goal") or "going about their day"


def secrets(npc: Npc) -> list[dict]:
    return cast.card(npc).get("secrets", [])


def stranger_lines(state: State, npc: Npc) -> list[str]:
    """What this person remembers of the stranger, for either model."""
    name, memory = npc["name"], knows(npc)
    lines = []
    if memory.get("name"):
        lines.append(f"The stranger has told {name} their name: {memory['name']}.")
    elif memory.get("heard_name"):
        lines.append(f"{name} has heard the stranger is called {memory['heard_name']}.")
    if memory.get("long_memory"):
        lines.append(f"Long ago: {memory['long_memory']}")
    for episode in memory.get("episodes", []):
        lines.append(f"An earlier conversation: {episode['text']}")
    for heard in memory.get("heard", [])[-4:]:
        lines.append(f"Heard from {heard['from_name']}: {heard['text']}")
    for claim in memory.get("claims", [])[-4:]:
        lines.append(f"The stranger claimed “{claim['text']}”, and {name} didn't believe it.")
    return lines


def current_talk(npc: Npc) -> list[dict]:
    """This conversation's turns (earlier conversations live on as episodes)."""
    since = knows(npc).get("since", 0)
    return [t for t in cast.mind(npc).get("talk", []) if t.get("at", 0) >= since]


def nearby(state: State, npc: Npc) -> list[dict]:
    return [
        n
        for n in state["npcs"]
        if n["id"] != npc["id"] and n.get("alive", True) and cast.distance(n, npc) <= NEARBY_CELLS
    ]


def opinion_lines(state: State, npc: Npc, people: list[dict] | None = None) -> list[str]:
    feelings = opinions(npc)
    lines = []
    for other in people if people is not None else nearby(state, npc):
        view = feelings.get(other["id"])
        if view:
            lately = f" Lately: {view['lately']}" if view.get("lately") else ""
            lines.append(f"{npc['name']} {warmth_words(view['warmth'])} {other['name']} ({view['text']}).{lately}")
    return lines


def shift_opinion(state: State, npc: Npc, who: str, change: str, why: str) -> dict | None:
    """Something said in a conversation changed how this person feels about someone else (D-59): by id or name,
    someone real and not themself. Returns {id, name, warmth} as it now stands, or None if nothing changed."""
    amount = tuning.OPINION_SHIFTS.get(change)
    other = cast.find(state["npcs"], who) or next(
        (n for n in state["npcs"] if n["name"].lower() == who.strip().lower()), None
    )
    if not amount or other is None or other["id"] == npc["id"]:
        return None
    view = opinions(npc).setdefault(
        other["id"], {"text": f"{other['name']} the {cast.card(other)['role']}", "warmth": 0.0}
    )
    view["warmth"] = round(max(-1.0, min(1.0, view["warmth"] + amount)), 2)
    if why:
        view["lately"] = why
    return {"id": other["id"], "name": other["name"], "warmth": view["warmth"]}


def usual_place(state: State, npc_id: str) -> str | None:
    """Where this person is usually found: the named place nearest their routine's first stop."""
    stops = npc_sim.anchors(state, npc_id)
    places = content.map_of(state)["places"].values()
    if not stops or not places:
        return None
    x, y = stops[0][0], stops[0][1]
    return min(places, key=lambda p: math.dist(p["cell"], (x, y)))["name"]


def everyone_in_town(state: State, npc: Npc) -> list[str]:
    """Everyone in a village this small knows everyone else (D-48): who they are and where they're usually found."""
    lines = []
    for other in state["npcs"]:
        if other["id"] == npc["id"]:
            continue
        place = usual_place(state, other["id"])
        relation = cast.relation(npc, other["id"])
        lines.append(
            f"{other['name']}, the {cast.card(other)['role']}"
            + (f" ({relation})" if relation else "")
            + (f", usually at {place}" if place else "")
            + ("" if other.get("alive", True) else ", now dead")
        )
    return lines


def sheet_lines(state: State, npc: Npc) -> list[str]:
    """The character sheet for the decider: who they are beyond their role, what they want, how they feel now."""
    me, name = cast.card(npc), npc["name"]
    lines = []
    if me.get("goals"):
        lines.append(f"What {name} wants right now: " + "; ".join(me["goals"]) + ".")
    if me.get("likes") or me.get("dislikes"):
        lines.append(f"{name} likes {me.get('likes', 'little')}; dislikes {me.get('dislikes', 'little')}.")
    if me.get("persuaded_by"):
        lines.append(f"What would change {name}'s mind: {me['persuaded_by']}.")
    if (me.get("superstition") or {}).get("text"):
        lines.append(f"Wonders and the uncanny: {me['superstition']['text']}")
    if me.get("style"):
        lines.append(f"How {name} talks: {me['style']}")
    lines.append(f"{name}'s mood: {mood(npc)}. {name} is {doing(npc)}.")
    for secret in secrets(npc):
        lines.append(f"(Private) {secret['text']} {name} would only let this out to {secret['reveal']}.")
    lines += opinion_lines(state, npc)
    lines.append(f"Everyone in town, whom {name} knows: " + "; ".join(everyone_in_town(state, npc)) + ".")
    return lines


def voice_sheet(state: State, npc: Npc) -> dict:
    """The same person, for the voice: how they sound, what they want and feel, who they know."""
    me = cast.card(npc)
    voice = me.get("voice") or {}
    return {
        "goals": me.get("goals", []),
        "concerns": me.get("concerns", ""),
        "likes": me.get("likes", ""),
        "dislikes": me.get("dislikes", ""),
        "mood": mood(npc),
        "doing": doing(npc),
        "authority": me.get("authority", ""),
        "wonders_and_the_uncanny": (me.get("superstition") or {}).get("text", ""),
        "how_they_talk": {
            "style": me.get("style", ""),
            "habits": voice.get("habits", ""),
            "greeting": voice.get("greeting", ""),
            "example_lines_never_copy": voice.get("samples", []),
            "would_never": voice.get("never", ""),
        },
        "people_they_know": opinion_lines(state, npc, [n for n in state["npcs"] if n["id"] in opinions(npc)]),
        "everyone_in_town": everyone_in_town(state, npc),
        "secrets_kept": [f"{s['text']} (only told to {s['reveal']})" for s in secrets(npc)],
        "remembers_the_stranger": stranger_lines(state, npc),
    }
