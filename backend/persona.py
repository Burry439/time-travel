"""One character sheet per person, read by the decider (Jev) and the voice alike (GDD D-38).

Personality used to be split: Jev never saw how someone talks or what persuades them, and the voice
never saw their goals or the people they know. Everything here comes from the authored card plus
what has happened to them: their mood, what they're doing, how they feel about the people around
them, and what they remember of the stranger (D-36). Free text from models only ever lands in
memory (notes, episodes); it never changes world state.
"""
from __future__ import annotations

import math

import minds

MOODS = ["content", "cheerful", "weary", "irritable", "anxious", "excited", "grieving"]
MOOD_WORDS = {m: m for m in MOODS}
NOTES_KEPT = 12  # Notes from the current conversation.
EPISODES_KEPT = 6  # Past conversations kept as short summaries; older ones merge into long_memory.
NEARBY_CELLS = 16


def knows(npc: dict) -> dict:
    """What this person has gathered about the stranger over every conversation (and from others)."""
    return minds.mind(npc).setdefault("knows", {"name": None, "notes": [], "claims": [], "episodes": [],
                                                "long_memory": "", "heard": [], "since": 0, "talks": 0})


def mood(npc: dict) -> str:
    return minds.mind(npc).get("mood") or minds.card(npc).get("mood") or "content"


def opinions(npc: dict) -> dict:
    """How they feel about the people they know; starts from the card, shifts as people talk (D-37)."""
    my_mind = minds.mind(npc)
    if "opinions" not in my_mind:
        my_mind["opinions"] = {k: dict(v) for k, v in minds.card(npc).get("opinions", {}).items()}
    return my_mind["opinions"]


def warmth_words(warmth: float) -> str:
    return "dislikes" if warmth <= -0.4 else "is wary of" if warmth < 0 else "is neutral about" if warmth < 0.2 \
        else "likes" if warmth < 0.6 else "is fond of"


def doing(npc: dict) -> str:
    return minds.mind(npc).get("doing") or (npc.get("controller") or {}).get("goal") or "going about their day"


def secrets(npc: dict) -> list[dict]:
    return minds.card(npc).get("secrets", [])


def stranger_lines(state: dict, npc: dict) -> list[str]:
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


def current_talk(npc: dict) -> list[dict]:
    """This conversation's turns (earlier conversations live on as episodes)."""
    since = knows(npc).get("since", 0)
    return [t for t in minds.mind(npc).get("talk", []) if t.get("at", 0) >= since]


def nearby(state: dict, npc: dict) -> list[dict]:
    return [n for n in state["npcs"] if n["id"] != npc["id"] and n.get("alive", True)
            and math.dist(minds._cell(n), minds._cell(npc)) <= NEARBY_CELLS]


def opinion_lines(state: dict, npc: dict, people: list[dict] | None = None) -> list[str]:
    feelings = opinions(npc)
    lines = []
    for other in (people if people is not None else nearby(state, npc)):
        view = feelings.get(other["id"])
        if view:
            lines.append(f"{npc['name']} {warmth_words(view['warmth'])} {other['name']} ({view['text']}).")
    return lines


def sheet_lines(state: dict, npc: dict) -> list[str]:
    """The character sheet for Jev: who they are beyond their role, what they want, how they feel now."""
    me, name = minds.card(npc), npc["name"]
    lines = []
    if me.get("goals"):
        lines.append(f"What {name} wants right now: " + "; ".join(me["goals"]) + ".")
    if me.get("likes") or me.get("dislikes"):
        lines.append(f"{name} likes {me.get('likes', 'little')}; dislikes {me.get('dislikes', 'little')}.")
    if me.get("persuaded_by"):
        lines.append(f"What would change {name}'s mind: {me['persuaded_by']}.")
    if me.get("style"):
        lines.append(f"How {name} talks: {me['style']}")
    lines.append(f"{name}'s mood: {mood(npc)}. {name} is {doing(npc)}.")
    for secret in secrets(npc):
        lines.append(f"(Private) {secret['text']} {name} would only let this out to {secret['reveal']}.")
    lines += opinion_lines(state, npc)
    return lines


def voice_sheet(state: dict, npc: dict) -> dict:
    """The same person, for the voice: how they sound, what they want and feel, who they know."""
    me = minds.card(npc)
    voice = me.get("voice") or {}
    return {
        "goals": me.get("goals", []),
        "concerns": me.get("concerns", ""),
        "likes": me.get("likes", ""),
        "dislikes": me.get("dislikes", ""),
        "mood": mood(npc),
        "doing": doing(npc),
        "authority": me.get("authority", ""),
        "how_they_talk": {"style": me.get("style", ""), "habits": voice.get("habits", ""),
                          "example_lines_never_copy": voice.get("samples", []),
                          "would_never": voice.get("never", "")},
        "people_they_know": opinion_lines(state, npc, [n for n in state["npcs"] if n["id"] in opinions(npc)]),
        "secrets_kept": [f"{s['text']} (only told to {s['reveal']})" for s in secrets(npc)],
        "remembers_the_stranger": stranger_lines(state, npc),
    }
