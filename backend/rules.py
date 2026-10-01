"""The one rule language content is written in (D-58): conditions that hold or don't in the world, each a small
registered function. The tutorial's steps and triggers, deals' done_when and people's tasks (when / unless) all
use it; so do the parked stories and secrets, which register their own kinds. Code decides every condition: a
model never says whether one holds (GDD 1).

A condition is {"kind": ..., ...its fields}; all, any and not combine them. ctx says whose rule it is ("npc", for
a person's task or secret) and where a scenario stands ("progress": when the step began, what was noticed).
The parts a scenario gives people (Kade the teacher staying with the stranger) are read here too: role().
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

import cast
import content
import gear
from shapes import State

SPAR_OUTCOMES = ("spar_won", "spar_lost", "spar_yielded")  # How a practice bout can end (combat.end_spar).
Condition = Callable[[State, dict, dict], bool]
CONDITIONS: dict[str, Condition] = {}
NEEDS: dict[str, tuple[str, ...]] = {}  # The fields each kind must have (the content check reads these).


def condition(kind: str, *needs: str) -> Callable[[Condition], Condition]:
    """Register a condition kind, fn(state, spec, ctx) -> bool, and the fields its spec must have."""

    def register(fn: Condition) -> Condition:
        CONDITIONS[kind] = fn
        NEEDS[kind] = needs
        return fn

    return register


def holds(state: State, spec: dict | None, ctx: dict | None = None) -> bool:
    """Whether a condition holds now. No condition always holds."""
    if spec is None:
        return True
    kind = spec["kind"]
    if kind not in CONDITIONS:
        raise ValueError(f"Unknown condition {kind}")
    return CONDITIONS[kind](state, spec, ctx or {})


def _progress(ctx: dict) -> dict:
    return ctx.get("progress") or {}


def _npc(state: State, spec: dict, ctx: dict, key: str = "npc"):
    """The person a condition is about: named in it, or the one whose rule it is."""
    return cast.find(state["npcs"], spec[key]) if spec.get(key) else ctx.get("npc")


# --- Combining ---------------------------------------------------------------------------------------------------


@condition("always")
def _always(state, spec, ctx):
    return True


@condition("all", "of")
def _all(state, spec, ctx):
    return all(holds(state, c, ctx) for c in spec["of"])


@condition("any", "of")
def _any(state, spec, ctx):
    return any(holds(state, c, ctx) for c in spec["of"])


@condition("not", "of")
def _not(state, spec, ctx):
    return not holds(state, spec["of"], ctx)


# --- Where a scenario stands -------------------------------------------------------------------------------------


@condition("flag", "key")
def _flag(state, spec, ctx):
    """Something the story noted (D-57): whether Kade told the captain the stranger wants in."""
    return bool(_progress(ctx).get("flags", {}).get(spec["key"]))


@condition("fired", "key")
def _fired(state, spec, ctx):
    """A step's trigger has happened ("step:trigger")."""
    return spec["key"] in _progress(ctx).get("fired", [])


@condition("step_time", "seconds")
def _step_time(state, spec, ctx):
    """A fallback: this long since the step began."""
    return state.get("sim_time_ms", 0) - _progress(ctx).get("started_at", 0) >= spec["seconds"] * 1000


@condition("ui", "key")
def _ui(state, spec, ctx):
    """Something the client reports the stranger did on screen (the pack opened, a closer look, the book read)."""
    return spec["key"] in _progress(ctx).get("ui_done", [])


# --- The stranger and what they carry ----------------------------------------------------------------------------


def carried(state: State) -> list[dict]:
    """What the stranger carries in the pack or hands (not what they wear)."""
    worn = {oid for slot, oid in (state["player"].get("equipped") or {}).items() if slot in gear.COVERS}
    return [o for o in state["objects"].values() if o.get("holder_id") == "player" and o["id"] not in worn]


def holding(state: State, kind: str) -> bool:
    """A weapon (or a shield...) in either of the stranger's hands."""
    return any(
        (obj := gear.held(state, state["player"], hand)) and gear.of(obj)["kind"] == kind for hand in gear.HAND_SLOTS
    )


@condition("near", "cell", "within")
def _near(state, spec, ctx):
    return math.dist(cast.player_cell(state), tuple(spec["cell"])) <= spec["within"]


@condition("carrying", "count")
def _carrying(state, spec, ctx):
    return len(carried(state)) >= spec["count"]


@condition("carrying_id", "ids")
def _carrying_id(state, spec, ctx):
    held = {o["id"] for o in carried(state)}
    return all(i in held for i in spec["ids"])


@condition("carrying_remedy", "treats")
def _carrying_remedy(state, spec, ctx):
    return any((remedy := gear.remedy_for(o)) and spec["treats"] in remedy["treats"] for o in carried(state))


@condition("holding_weapon")
def _holding_weapon(state, spec, ctx):
    return holding(state, "weapon")


@condition("holding_shield")
def _holding_shield(state, spec, ctx):
    return holding(state, "shield")


@condition("admitted")
def _admitted(state, spec, ctx):
    return bool(state.get("admitted"))


# --- People ------------------------------------------------------------------------------------------------------


@condition("able")
def _able(state, spec, ctx):
    """Alive and on their feet."""
    npc = _npc(state, spec, ctx)
    return bool(npc) and npc.get("alive", True) and not npc.get("down")


@condition("npc_near", "npc", "within")
def _npc_near(state, spec, ctx):
    npc = _npc(state, spec, ctx)
    return bool(npc) and npc.get("alive", True) and cast.distance(npc, state["player"]) <= spec["within"]


@condition("talked_to", "npc")
def _talked_to(state, spec, ctx):
    """The stranger has said something to them (since_step: since this step began, D-57)."""
    npc = _npc(state, spec, ctx)
    since = _progress(ctx).get("started_at", 0) if spec.get("since_step") else -1
    return bool(npc) and any(
        t.get("who") == "stranger" and t.get("at", 0) >= since for t in (npc.get("mind") or {}).get("talk", [])
    )


@condition("said_to", "words")
def _said_to(state, spec, ctx):
    """The stranger's own words to them included any of these (whole words, any case)."""
    npc = _npc(state, spec, ctx)
    words = re.compile(r"\b(" + "|".join(re.escape(w) for w in spec["words"]) + r")\b", re.IGNORECASE)
    return bool(npc) and any(
        t.get("who") == "stranger" and words.search(str(t.get("text", "")))
        for t in (npc.get("mind") or {}).get("talk", [])
    )


@condition("heard_from", "npc", "from")
def _heard_from(state, spec, ctx):
    """Someone has come and told them (an errand, D-51), at least after_s seconds ago."""
    npc = _npc(state, spec, ctx)
    wait = spec.get("after_s", 0) * 1000
    return bool(npc) and any(
        h.get("from") == spec["from"] and state.get("sim_time_ms", 0) - h.get("at", 0) >= wait
        for h in (npc.get("mind") or {}).get("knows", {}).get("heard", [])
    )


@condition("condition_treated", "npc", "condition")
def _condition_treated(state, spec, ctx):
    """None of their wounds of this kind is left untreated."""
    npc = _npc(state, spec, ctx)
    wounds = [c for c in (npc or {}).get("conditions", []) if c["kind"] == spec["condition"]]
    return bool(npc) and (not wounds or all(c.get("treated", 0) > 0 for c in wounds))


@condition("ready_to_spar", "npc", "within")
def _ready_to_spar(state, spec, ctx):
    npc = _npc(state, spec, ctx)
    return (
        bool(npc)
        and npc.get("alive", True)
        and not npc.get("down")
        and not state.get("fight")
        and holding(state, "weapon")
        and cast.distance(npc, state["player"]) <= spec["within"]
    )


@condition("bout_over")
def _bout_over(state, spec, ctx):
    return any(e.get("kind") == "fight" and e.get("category") in SPAR_OUTCOMES for e in state.get("journal", []))


@condition("demonstration_seen")
def _demonstration_seen(state, spec, ctx):
    return any(
        m.get("kind") == "demonstration" and m.get("works", True) and m.get("clarity") == "clear"
        for n in state["npcs"]
        for m in (n.get("mind") or {}).get("memories", [])
    )


@condition("made_seen", "flag", "by")
def _made_seen(state, spec, ctx):
    """Something with this flag made by the stranger in this step, and this person saw it."""
    progress = _progress(ctx)
    made = any(
        o.get("created_by") == "player"
        and spec["flag"] in o.get("flags", [])
        and int(o.get("created_event_id") or 0) > progress.get("started_seq", 0)
        for o in state["objects"].values()
    )
    npc = _npc(state, spec, ctx, "by")
    return (
        made
        and bool(npc)
        and any(
            m.get("kind") == "demonstration"
            and m.get("clarity") != "vague"
            and m.get("at", 0) >= progress.get("started_at", 0)
            for m in (npc.get("mind") or {}).get("memories", [])
        )
    )


@condition("vouched", "npc")
def _vouched(state, spec, ctx):
    """This person has spoken for the stranger to the captain."""
    captain = cast.captain(state)
    return bool(captain) and any(
        m.get("kind") == "vouch" and m.get("by") == spec["npc"] for m in (captain.get("mind") or {}).get("memories", [])
    )


@condition("asked_device")
def _asked_device(state, spec, ctx):
    """The stranger asked the device something in this step (H)."""
    since = _progress(ctx).get("started_at", 0)
    return any(e.get("question") and e.get("at", 0) >= since for e in state.get("device_log", []))


@condition("attempt_failed")
def _attempt_failed(state, spec, ctx):
    """Something the stranger tried in this step didn't work, and the world said why (D-59: learning to read it)."""
    since = _progress(ctx).get("started_seq", 0)
    return any(
        e.get("kind") == "craft" and e.get("category") in ("failed", "blocked") and int(e.get("event_id") or 0) > since
        for e in state.get("journal", [])
    )


# --- Things ------------------------------------------------------------------------------------------------------


def _made_here(obj: dict, since: int) -> bool:
    return obj.get("created_by") == "player" and int(obj.get("created_event_id") or 0) > since


@condition("made", "named")
def _made(state, spec, ctx):
    """The stranger made something in this step whose name has one of these words (a rope, a torch): however they
    put it, whatever the judge called it."""
    since = _progress(ctx).get("started_seq", 0)
    return any(
        _made_here(o, since) and any(word in o["name"].lower() for word in spec["named"])
        for o in state["objects"].values()
    )


@condition("gave_made", "npc", "count")
def _gave_made(state, spec, ctx):
    """This person has at least this many things the stranger made (given to them)."""
    npc = _npc(state, spec, ctx)
    held = [
        o for o in state["objects"].values() if o.get("created_by") == "player" and npc and o["holder_id"] == npc["id"]
    ]
    return len(held) >= spec["count"]


@condition("filled", "thing")
def _filled(state, spec, ctx):
    """This thing holds water (a cup filled at the well)."""
    return float((state["objects"].get(spec["thing"]) or {}).get("water_l") or 0) > 0


@condition("held_by", "thing", "npc")
def _held_by(state, spec, ctx):
    """This person has this thing (given to them)."""
    return (state["objects"].get(spec["thing"]) or {}).get("holder_id") == spec["npc"]


# --- Things ------------------------------------------------------------------------------------------------------


@condition("installed", "thing")
def _installed(state, spec, ctx):
    """This thing is fitted in place (the new beam up in the gate's brackets)."""
    return bool((state["objects"].get(spec["thing"]) or {}).get("installed_in"))


# --- The parts a scenario gives people ---------------------------------------------------------------------------


def scene_step(state: State) -> dict | None:
    """The step the journey's guided story is on, if one is running on this version of it."""
    progress = state.get("tutorial")
    story = content.level(state)
    if not progress or progress.get("done") or not story.get("steps") or progress.get("version", 2) != story["version"]:
        return None
    return story["steps"][progress["step"]]


def note_fired(state: State, keys: list[str]) -> None:
    """The story's own triggers these stand for have happened (a bout begun by a blow instead of by walking up)."""
    progress = state.get("tutorial")
    if progress is not None:
        progress.setdefault("fired", []).extend(keys)


def role(state: State, npc: dict) -> dict:
    """What the running scenario asks of this person right now: Kade, during his lessons, stays with the stranger,
    won't go off on errands and spars when struck (D-53, D-57). {} when it asks nothing. The one place core rules
    (talk, fights, the clock) learn about a scenario; they never ask which scenario it is."""
    current = scene_step(state)
    if current is None:
        return {}
    for part in content.level(state).get("roles", []):
        if part["npc"] == npc["id"] and current["id"] in part["during"]:
            return part
    return {}
