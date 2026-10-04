"""Who's who and where: each person's card and mind, finding people, where they stand, the job they're on,
and who has something to think about next. Every module about people stands on this one (GDD section 8)."""

from __future__ import annotations

import math

import content
import gear
from shapes import Job, Mind, Npc, State

CARDS: dict[str, dict] = content.CARDS


def captain_id(state: State) -> str | None:
    """The captain here: whoever in this level decides who enters (their card holds decides, D-43); None if
    nobody does."""
    return next((npc["id"] for npc in state["npcs"] if CARDS.get(npc["id"], {}).get("decides")), None)


def robbing(npc: Npc | None) -> bool:
    """A robber still after the stranger's things (D-59): their card says what they rob, and they haven't stood
    aside (paid, talked round, scared off, or done)."""
    return bool(npc) and bool(card(npc).get("robs")) and not mind(npc).get("stood_aside")


def captain(state: State) -> Npc | None:
    return find(state["npcs"], captain_id(state) or "")


def card(npc: Npc) -> dict:
    return CARDS.get(
        npc["id"],
        {
            "name": npc["name"],
            "role": npc["role"],
            "guard": False,
            "weapon": None,
            "combat": "no fighter",
            "personality": "",
            "values": "",
            "fears": "",
            "authority": "",
            "armor": "none",
            "tones": ["frightened"],
            "relations": {},
            "family": [],
        },
    )


ERRAND_JOBS = ("tell", "vouch", "report")  # Jobs that take someone somewhere to do something (D-54).


def add_errand(npc: Npc, job: dict, now: int) -> None:
    """Send them on an errand; one already on an errand goes on this one after it (D-63: Darin, agreeing to pay
    Hessa after agreeing to let Oren's debt go, set off for the inn and never told Oren)."""
    current = mind(npc).get("job") or {}
    if current.get("kind") in ERRAND_JOBS:
        current.setdefault("next_errands", []).append(job)
    else:
        set_job(npc, job, now)


def mind(npc: Npc) -> Mind:
    return npc.setdefault("mind", {"memories": [], "feelings": {"fear": 0.0, "anger": 0.0}, "job": None, "said": None})


def find(npcs: list[Npc], npc_id: str) -> Npc | None:
    return next((n for n in npcs if n["id"] == npc_id), None)


def player_cell(state: State) -> tuple[int, int]:
    return state["player"]["x"], state["player"]["y"]


def cell(npc: Npc) -> tuple[int, int]:
    return npc["x"], npc["y"]


def offer_of(state: State, deal: dict) -> dict:
    """The offer on the issuer's card a deal came from ({} if it's gone)."""
    issuer = find(state["npcs"], deal.get("issuer") or "")
    return next((o for o in (card(issuer).get("offers", []) if issuer else []) if o["id"] == deal.get("template")), {})


def distance(a, b) -> float:
    """How far apart two people, things or cells are: anything with an x and a y, or an (x, y) pair."""
    return math.dist(_at(a), _at(b))


def nearest(thing: dict, frm) -> tuple[int, int]:
    """Where a thing is, as seen from somewhere: its cell, or the nearest cell of the area it spreads over (a lake, a
    river: D-59, a lake was one point, so water was out of reach from much of its own shore)."""
    if not thing.get("area"):
        return thing["x"], thing["y"]
    x, y, w, h = thing["area"]
    fx, fy = _at(frm)
    return min(max(round(fx), x), x + w - 1), min(max(round(fy), y), y + h - 1)


def _at(where) -> tuple:
    return (where["x"], where["y"]) if isinstance(where, dict) else where


def armed_with(state: State, npc: Npc) -> str | None:
    """What this person is armed with, in words: their own weapon as their card names it, anything else they've
    picked up by its name, or None when their hands hold no weapon (D-49: what they have now, not what they began
    with)."""
    obj = gear.weapon_in_hand(state, npc)
    if obj is None:
        return None
    own = card(npc).get("weapon") if obj.get("owner_id") == npc["id"] else None
    return own or obj["name"]


def condition(health: float, alive: bool = True) -> str:
    if not alive:
        return "dead"
    return "unhurt" if health >= 100 else "wounded" if health > 30 else "badly wounded (near death)"


def relation(npc: Npc, other_id: str | None) -> str | None:
    """How this person refers to someone they know, e.g. 'her nephew Jory'."""
    return card(npc).get("relations", {}).get(other_id or "")


def is_family(npc: Npc, other_id: str | None) -> bool:
    return (other_id or "") in card(npc).get("family", [])


def watch(npc: Npc, now: int, ms: int) -> None:
    """Keep an eye on the stranger for a while: after a fright, a fight, a job done or a conversation over."""
    set_job(npc, {"kind": "watch", "until": now + ms}, now)


def add_pending(state: State, npc_id: str, kind: str = "decide", why: str = "") -> None:
    pending = state.setdefault("pending_minds", [])
    if not any(p["npc_id"] == npc_id and p["kind"] == kind for p in pending):
        pending.append({"npc_id": npc_id, "kind": kind, "why": why})


REACTING = ("decide",)  # Pending kinds that mean someone is reacting to the stranger.


def calm(state: State) -> bool:
    """No one is reacting to the player: a safe point to rewind to (people planning their day don't count)."""
    if any(p["kind"] in REACTING for p in state.get("pending_minds", [])) or not state["player"].get("alive", True):
        return False
    if state.get("encounter") and state["encounter"].get("reason") != "talk" or state.get("fight"):
        return False
    return not any(
        (npc.get("mind") or {}).get("job")
        and npc["mind"]["job"]["kind"] in ("attack", "fight", "report", "flee", "approach")
        for npc in state["npcs"]
    )


def set_job(npc: Npc, job: Job | None, now: int) -> None:
    mind(npc)["job"] = job
    controller = npc.get("controller")
    if controller is None:
        return
    if job is None:
        controller.update(source="routine", activity="look", path=[], next_at_ms=now + 1500, step_carry_ms=0)
    else:
        controller.update(
            source="job",
            path=[],
            step_carry_ms=0,
            activity="walk"
            if job["kind"] in ("flee", "report", "approach", "attack", "vouch", "tell", "fight")
            else "look",
        )
        if job["kind"] in ("encounter", "watch", "attack", "fight") or job.get("target") == "player":
            mind(npc)["facing_player"] = True  # Busy with the stranger: they keep an eye on them.


def aware(state: State, npc: Npc) -> bool:
    """Is this person watching the stranger (facing them, busy with them, or fighting them)? If not, they can
    be taken by surprise."""
    my_mind = npc.get("mind") or {}
    return bool(
        my_mind.get("facing_player")
        or my_mind.get("job")
        and my_mind["job"].get("target") == "player"
        or npc["id"] in ((state.get("fight") or {}).get("attackers") or [])
    )
