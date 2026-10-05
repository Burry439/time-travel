"""What the client shows that's worked out from the world, worked out once, here (D-58): whether each lead is done,
the journey's deeds, the storylines the stranger has come into (D-61), and the words for where people stand. Every state a route returns carries it as
state["view"], added at the last moment and never saved, so the client renders and never re-derives game rules.
"""

from __future__ import annotations

import contextlib
import functools
import inspect

from fastapi import HTTPException
from fastapi.routing import APIRoute

import cast
import effects
import gatekeeping
import gear
import reputation
import rules
import stories
from shapes import State


def of(state: State) -> dict:
    return {
        "lead_done": [lead_done(state, claim) for claim in state.get("learned", [])],  # One for each learned.
        "deeds": deeds(state),
        "stories": stories.page(state),
        "standing_words": reputation.STANDING_WORDS,
        "gear": {
            obj["id"]: {
                "profile": gear.weapon(obj),
                "record": gear.of(obj),
                "words": gear.words(obj),
                "slots": gear.slots_for(obj),
                "equip_seconds": {slot: gear.equip_seconds(obj, slot) for slot in gear.slots_for(obj)},
            }
            for obj in state.get("objects", {}).values()
            if obj.get("holder_id")
            and not effects.gone(obj)
            and not effects.unseen_by(obj, "player")
            and not effects.shut_in(state, obj)
        },
    }


# --- Leads -------------------------------------------------------------------------------------------------------


def lead_done(state: State, claim: dict) -> bool:
    """Whether what something the stranger learned points to has happened: a deal done, a loan returned, a person
    met (a gift or a trade is done when it's learned)."""
    if "fulfilled" in claim or "gift" in claim or "trade" in claim or "story" in claim:
        return True
    if claim.get("done_when"):  # Something a story asked of the stranger (D-59): done when its condition holds.
        return rules.holds(state, claim["done_when"])
    if "offer" in claim:
        return (state.get("agreements") or {}).get(str(claim["offer"]), {}).get("status") == "fulfilled"
    if "lend" in claim:
        thing = state.get("objects", {}).get(str(claim["lend"]), {})
        return thing.get("holder_id") == claim.get("npc_id") or thing.get("lent_to") != "player"
    if claim.get("refer") is not None:
        npc = cast.find(state["npcs"], str(claim["refer"]))
        return bool(npc and (npc.get("mind") or {}).get("met", False))
    return False


# --- Deeds (D-55) ------------------------------------------------------------------------------------------------


def deeds(state: State) -> list[dict]:
    """The milestones of a journey, read from what really happened (never arbitrary achievements): the first
    invention, someone amazed, someone helped, someone who would speak for you, someone who did, word spreading, a
    deal agreed and kept, the gate opening. (How warm each person is shows as their standing, not as a deed.)
    Each: {id, title, text, who (a person id or "")}."""
    found = []
    names = {npc["id"]: npc["name"] for npc in state.get("npcs", [])}
    made = [o for o in state.get("objects", {}).values() if o.get("created_by") == "player"]
    if made:
        text = f"You made a {made[0]['name']}. Nobody in this world had one until you did."
        found.append(_deed("first_made", "Your first invention", text, ""))
    for npc in state.get("npcs", []):
        found += _deeds_of(npc, names)
    for deal in (state.get("agreements") or {}).values():
        issuer = str(deal.get("issuer", ""))
        if deal.get("status") in ("accepted", "fulfilled"):
            text = f"You agreed to {deal.get('task', 'help')}."
            found.append(_deed(f"deal:{deal['id']}", f"A deal with {names.get(issuer, 'someone')}", text, issuer))
        if deal.get("status") == "fulfilled":
            text = f"{names.get(issuer, 'They')} is satisfied: you did what you promised."
            found.append(_deed(f"kept:{deal['id']}", "You kept your word", text, issuer))
    if isinstance(state.get("admitted"), dict) or state.get("inside_city"):
        title, text = gatekeeping.words(state)["deed"]
        found.append(_deed("admitted", title, text, ""))
    return found


def _deeds_of(npc: dict, names: dict) -> list[dict]:
    """What one person's memories (and standing) make deeds of."""
    found, me, name = [], npc["id"], npc["name"]
    memories = (npc.get("mind") or {}).get("memories", [])
    amazed = next(
        (
            m
            for m in memories
            if m.get("kind") == "demonstration"
            and m.get("wonder") in ("clever", "uncanny")
            and m.get("clarity") == "clear"
        ),
        None,
    )
    if amazed:
        item = amazed.get("item") or "invention"
        text = f"{name} saw your {item} work, and has never seen anything like it."
        found.append(_deed(f"amazed:{me}", f"{name} was amazed", text, me))
    if any(
        m.get("kind") in ("help", "gift") and m.get("victim") == me and m.get("clarity") != "vague" for m in memories
    ):
        found.append(_deed(f"helped:{me}", f"You helped {name}", f"{name} won't forget it.", me))
    if (npc.get("mind") or {}).get("standing") == "would_speak":
        text = f"Ask, and {name} would put in a word for you."
        found.append(_deed(f"would_speak:{me}", f"{name} would speak for you", text, me))
    for m in memories:
        if m.get("kind") == "vouch":
            by = str(m.get("by", ""))
            who = names.get(by, "Someone")
            found.append(
                _deed(f"vouched:{by}:{me}", f"{who} spoke for you", f"{who} went to {name} and spoke for you.", by)
            )
        if m.get("kind") == "told":
            teller = str(m.get("by", ""))
            who = names.get(teller, "Someone")
            found.append(_deed(f"news:{teller}:{me}", "Word is spreading", f"{who} told {name} about you.", teller))
    return found


def _deed(deed_id: str, title: str, text: str, who: str) -> dict:
    return {"id": deed_id, "title": title, "text": text, "who": who}


# --- Every reply that carries a state carries its view ----------------------------------------------------------


def shown(reply):
    """A reply with its state's view added (a state itself, or {"state": ...}); anything else as it is."""
    if isinstance(reply, dict) and "npcs" in reply and "objects" in reply:
        return {**reply, "view": of(reply)}
    if isinstance(reply, dict) and isinstance(reply.get("state"), dict) and "npcs" in reply["state"]:
        return {**reply, "state": shown(reply["state"])}
    return reply


@contextlib.contextmanager
def _refusals_shown():
    """A refusal that carries the world (a blocked step, a stale view) carries its view too."""
    try:
        yield
    except HTTPException as refusal:
        if isinstance(refusal.detail, dict) and isinstance(refusal.detail.get("state"), dict):
            refusal.detail = {**refusal.detail, "state": shown(refusal.detail["state"])}
        raise


class Shown(APIRoute):
    """The route class every router uses: its endpoint's reply goes out with the view."""

    def __init__(self, path: str, endpoint, **kwargs):
        if inspect.iscoroutinefunction(endpoint):

            @functools.wraps(endpoint)
            async def with_view(*args, **kw):
                with _refusals_shown():
                    return shown(await endpoint(*args, **kw))
        else:

            @functools.wraps(endpoint)
            def with_view(*args, **kw):
                with _refusals_shown():
                    return shown(endpoint(*args, **kw))

        super().__init__(path, with_view, **kwargs)
