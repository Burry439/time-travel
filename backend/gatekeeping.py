"""Who may let the stranger into the city, and when (D-43, D-55): any guard for their own reasons, never while
they know of a crime by the stranger or while the stranger is barred; the captain on a legitimate reason,
with someone's word for them. Speaking for the stranger to the captain is here too."""

from __future__ import annotations

import cast
import content
from shapes import Npc, State

# How a level speaks of getting in (D-59): the village's gate, unless the map names its own way in (a ferry across a
# river, a manor's gate). Each is a whole phrase, so the village's words stay exactly as they were.
ENTRY = {
    "place": "the city",  # Who may enter {place}; a threat to {place}; let the stranger into {place}.
    "decider": "the captain",  # Speak for the stranger to {decider}.
    "title": "Captain",  # {name} goes to {title} {decider's name} now.
    "admit": "admits the stranger into the city and orders the gate opened for them",
    "let_through": "lets the stranger through the gate on their own say-so, and has it opened for them",
    "let_in": "let in: the gate is open to them, but they haven't walked through it yet",
    "arrived": "inside the city",
    "deed": ["The gate opens", "You're allowed into the city."],
    "fallback_admit": "Very well. Open the gate for this one.",
    "fallback_vouch": "Right. I'll go and have a word with the captain for you.",
}


def words(state: State) -> dict:
    """This level's words for getting in: the map's own (entry), over the village's."""
    return {**ENTRY, **(content.map_of(state).get("entry") or {})}


def decider_called(state: State, decider: Npc) -> str:
    """'Captain Varo', or just 'Gorm' where the one who decides has no title."""
    return f"{words(state)['title']} {decider['name']}".strip()


def barred(state: State) -> bool:
    return (state.get("barred_until") or 0) > state.get("sim_time_ms", 0)


def admission_rule(npc: Npc) -> str:
    """How this person decides who may pass the gate, in their own terms (the captain's is 'decides')."""
    me = cast.card(npc)
    return me.get("decides") or me.get("admits") or ""


def can_admit(state: State, npc: Npc) -> bool:
    """Any guard with their own reasons (D-43), conscious and alive, for a living stranger not yet admitted. A known
    crime, a barred gate or a stranger with nothing to show are theirs to weigh (D-62): permission is not the
    physical way in, which a barred gate still shuts."""
    return (
        bool(cast.card(npc).get("guard") and admission_rule(npc))
        and not npc.get("down")
        and npc.get("alive", True)
        and not state.get("admitted")
        and state["player"].get("alive", True)
    )


def grounds_to_admit(npc: Npc) -> bool:
    """Whether this guard has a rule of their own to admit by. Since D-62 the evidence behind a yes is the guard's to
    weigh in their own call (who_they_would_let_through, and their own evidence ledger), not a code threshold; the
    reply's own reading must still agree with the move (conversation.admits_now)."""
    return bool(admission_rule(npc))


def speak_for(state: State, npc: Npc, why: str, summary: str, event_id: int, now: int) -> None:
    """The person walks to the captain and speaks for the stranger (minds.advance_world delivers it). Nobody to
    speak to in a level without a captain."""
    if (captain := cast.captain_id(state)) is None:
        return
    cast.set_job(
        npc,
        {"kind": "vouch", "target": captain, "speed": "walk", "why": why, "summary": summary, "event": event_id},
        now,
    )
