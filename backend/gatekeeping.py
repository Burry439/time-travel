"""Who may let the stranger into the city, and when (D-43, D-55): any guard for their own reasons, never while
they know of a crime by the stranger or while the stranger is barred; the captain on a legitimate reason,
with someone's word for them. Speaking for the stranger to the captain is here too."""

from __future__ import annotations

import cast
import reputation
from shapes import Npc, State


def barred(state: State) -> bool:
    return (state.get("barred_until") or 0) > state.get("sim_time_ms", 0)


def admission_rule(npc: Npc) -> str:
    """How this person decides who may pass the gate, in their own terms (the captain's is 'decides')."""
    me = cast.card(npc)
    return me.get("decides") or me.get("admits") or ""


def can_admit(state: State, npc: Npc) -> bool:
    """Any guard with their own reasons (D-43), standing, for a living stranger who isn't barred, never after
    violence or an assault on the gate they know of."""
    return (
        bool(cast.card(npc).get("guard") and admission_rule(npc))
        and not npc.get("down")
        and npc.get("alive", True)
        and not state.get("admitted")
        and state["player"].get("alive", True)
        and not reputation.knows_a_crime(npc)
        and not barred(state)
    )


def grounds_to_admit(npc: Npc) -> bool:
    """Something real behind letting the stranger in, never their word alone (D-55): evidence this guard holds
    (a resident's word given in person, something shown to work, a gift, help they saw). A guard going on their
    own motive may also go on trust earned over time; the captain's rule asks for the evidence."""
    if any(reputation.is_evidence(m) for m in cast.mind(npc).get("memories", [])):
        return True
    return not cast.card(npc).get("decides") and reputation.standing(npc) in ("friendly", "would_speak")


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
