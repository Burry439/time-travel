"""The world's vocabulary (D-65): general building blocks the judge composes for any deed.

Each block works on anything and anyone it makes sense for (things, people including the stranger, water), and
has three parts: a law in code (`check`: reach, strength, conservation, protected names, bounded values), a
reducer (`apply`: what changes in the world), and a consumer (`noticed_by`: who or what reads the change, so it
matters). The open-ended part is data the AI supplies: the names and values of marks and states, the text of
writing, what a state stops someone doing. Models read them back (the judge, each person's own call); code never
lets an effect write into anyone's mind. A block isn't done until all three parts exist, and the content test
holds every registered kind to that.

Families (GDD D-65): F bodies, H information, J touch and gesture and the open attribute (phase 1); B place and
structure, C containers and mixtures, A matter (phase 2). Signals, terrain, fire and processes follow.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import cast
import paths
import tuning
from shapes import State

# What a state can stop someone doing (code enforces each): walking, seeing (so they witness nothing by sight),
# speaking (no spoken line), using their hands (no making, taking or blows).
LIMITS = ("move", "see", "speak", "hands")

# Names an effect may never set on a person: their mind, standing and body numbers are theirs and the engine's.
PERSON_PROTECTED = {
    "trust",
    "suspicion",
    "respect",
    "awe",
    "fear",
    "anger",
    "feelings",
    "mind",
    "memory",
    "memories",
    "opinion",
    "opinions",
    "standing",
    "health",
    "alive",
    "down",
    "admitted",
    "permission",
    "owner",
    "owner_id",
    "holder_id",
    "name",
    "role",
}

MAX_STATE_MINUTES = 24 * 60
MAX_TEXT = 300


@dataclass(frozen=True)
class Block:
    """One building block: its family, the parameters it needs, its law, its reducer, and who notices it."""

    kind: str
    family: str
    needs: tuple[str, ...]
    noticed_by: str
    check: Callable[[State, dict, dict], str | None]
    apply: Callable[..., None]


REGISTRY: dict[str, Block] = {}


def block(kind: str, family: str, needs: tuple[str, ...], noticed_by: str):
    """Register a block: decorate its check; its apply is registered with `reducer`."""

    def register(check):
        REGISTRY[kind] = Block(kind, family, needs, noticed_by, check, _no_change)
        return check

    return register


def reducer(*kinds: str):
    """Register the reducer of one or more blocks: apply(world, effect, now, actor_id, repaint)."""

    def register(apply):
        for kind in kinds:
            old = REGISTRY[kind]
            REGISTRY[kind] = Block(old.kind, old.family, old.needs, old.noticed_by, old.check, apply)
        return apply

    return register


def alias(kind: str, like: str, noticed_by: str | None = None) -> None:
    """A second block with the same law as another (disconnect as connect, mark as write)."""
    old = REGISTRY[like]
    REGISTRY[kind] = Block(kind, old.family, old.needs, noticed_by or old.noticed_by, old.check, old.apply)


def _no_change(state: State, effect: dict, now: int, actor_id: str, repaint=None) -> None:
    """Nothing in the world changes: it's seen (touch, gesture), and the people it touches decide what it means."""


# --- Who and what an effect can touch ------------------------------------------------------------------------------


def person(state: State, person_id: str | None) -> dict | None:
    """The stranger ("player") or someone in the world, alive."""
    if not person_id:
        return None
    found = state["player"] if person_id == "player" else cast.find(state["npcs"], person_id)
    return found if found is not None and found.get("alive", True) else None


def actor(state: State, ctx: dict) -> dict:
    return person(state, ctx.get("actor_id", "player")) or state["player"]


def in_reach(state: State, ctx: dict, someone: dict) -> bool:
    """Close enough to touch: arm's reach of where the actor is (after any walk the step planned)."""
    me = actor(state, ctx)
    return someone is me or cast.distance(me, someone) <= tuning.REACH_CELLS + 0.5


def thing(state: State, ctx: dict, thing_id: str | None) -> dict | None:
    """A thing the actor can work on: anything in the judge's available items, or a water source at hand."""
    if not thing_id:
        return None
    return ctx["available"].get(thing_id) or ctx.get("water", {}).get(thing_id)


def target(state: State, ctx: dict, target_id: str | None) -> tuple[str, dict] | None:
    """("person", them) or ("thing", it), whichever the id names and the actor can reach."""
    someone = person(state, target_id)
    if someone is not None:
        return ("person", someone) if in_reach(state, ctx, someone) else None
    found = thing(state, ctx, target_id)
    return ("thing", found) if found is not None else None


# --- The laws ----------------------------------------------------------------------------------------------------------


def check(state: State, effects: list[dict], ctx: dict) -> str | None:
    """Every effect a step proposes, against the world: the first problem, or None. ctx: available (things by id),
    water (water sources by id), actor_id, resources (ids the step may cite as a basis)."""
    for effect in effects:
        kind = effect.get("kind")
        if kind not in REGISTRY:
            return f"unknown effect kind {kind!r}"
        missing = [n for n in REGISTRY[kind].needs if not effect.get(n)]
        if missing:
            return f"{kind} needs {', '.join(missing)}"
        problem = REGISTRY[kind].check(state, effect, ctx)
        if problem:
            return f"{kind}: {problem}"
    return None


def _named(name: str | None, protected: set[str], most: int = 80) -> str | None:
    name = (name or "").strip()
    if not name or len(name) > most:
        return "a name of 1 to 80 characters"
    if name.lower() in protected:
        return f"'{name}' is not something a deed can set"
    return None


@block("attribute", "open", ("target_id", "attribute"), "the judge, each person's own call, inspect cards, pictures")
def _check_attribute(state, effect, ctx):
    """Any named physical fact on a thing, a person or water (chalk dust, a carved groove, smelling of the trough)."""
    import crafting

    found = target(state, ctx, effect["target_id"])
    if found is None:
        return "the target isn't within reach"
    attribute = effect["attribute"]
    protected = crafting.PROTECTED_ATTRIBUTES | (PERSON_PROTECTED if found[0] == "person" else set())
    problem = _named(attribute.get("name"), protected)
    if problem:
        return problem
    if len(attribute.get("value", "")) > 400:
        return "a value of at most 400 characters"
    basis = attribute.get("basis_ids") or []
    real = set(ctx["available"]) | set(ctx.get("water", {})) | {"player"} | {n["id"] for n in state["npcs"]}
    if not basis or any(i not in real for i in basis):
        return "a real causal basis (the things or people that made it so)"
    return None


@block(
    "connect",
    "structure",
    ("target_id", "other_id"),
    "assemblies take what's attached; cutting a tied thing is refused",
)
def _check_connect(state, effect, ctx):
    if effect["target_id"] == effect["other_id"]:
        return "two distinct things"
    if not (thing(state, ctx, effect["target_id"]) and thing(state, ctx, effect["other_id"])):
        return "both things within reach"
    return None


alias("disconnect", "connect")


@block(
    "condition", "bodies", ("target_id", "name"), "their own call (how they are), what they can do (limits), onlookers"
)
def _check_condition(state, effect, ctx):
    """A state on a person: soaked, filthy, drunk, asleep, tied up, gagged, blindfolded, disguised. What it stops
    them doing is its limits; it ends after its minutes (0: until something ends it)."""
    someone = person(state, effect["target_id"])
    if someone is None or not in_reach(state, ctx, someone):
        return "a living person within reach"
    problem = _named(effect["name"], PERSON_PROTECTED, 40)
    if problem:
        return problem
    if len(effect.get("value") or "") > 200:
        return "a description of at most 200 characters"
    if not 0 <= int(effect.get("minutes") or 0) <= MAX_STATE_MINUTES:
        return f"minutes between 0 and {MAX_STATE_MINUTES}"
    if any(limit not in LIMITS for limit in effect.get("limits") or []):
        return f"limits only from {', '.join(LIMITS)}"
    if {"move", "hands"} & set(effect.get("limits") or []) and not _overpowered(state, ctx, someone):
        return "they won't stand still for it: they'd have to be down, asleep, blindfolded, already bound, or willing"
    return None


def _overpowered(state: State, ctx: dict, someone: dict) -> bool:
    """Whether someone could be tied, held or otherwise stopped from walking or using their hands: themselves,
    or someone down, asleep or blindfolded (a state that stops them seeing), already bound, or who has agreed to it
    (an accepted commitment). A conscious, standing person who hasn't agreed fights it off (D-65)."""
    if someone is actor(state, ctx) or someone.get("down"):
        return True
    if limited(someone, "see") or limited(someone, "move") or limited(someone, "hands"):
        return True
    return any(c.get("status") == "accepted" for c in (someone.get("mind") or {}).get("commitments", []))


@block("end_condition", "bodies", ("target_id", "name"), "their own call; what they could not do, they can again")
def _check_end_condition(state, effect, ctx):
    """A state ends: untied, woken, dried off, the blindfold taken off."""
    someone = person(state, effect["target_id"])
    if someone is None or not in_reach(state, ctx, someone):
        return "a living person within reach"
    if not _state_named(someone, effect["name"]):
        return f"{someone.get('name', 'they')} isn't '{effect['name']}'"
    return None


@block("consume", "matter", ("target_id",), "the thing is gone; whoever ate or drank it has it in their own call")
def _check_consume(state, effect, ctx):
    """Something eaten, drunk, burnt up or otherwise used up. What it does to a body is a condition beside it.
    Water consumed (a trough, a full cup) is drunk: a transfer into whoever drinks it (live: "drink from the trough")."""
    found = thing(state, ctx, effect["target_id"])
    if found is None:
        return "the thing within reach"
    if _water_in(found):
        return _check_transfer(state, _as_drink(effect, ctx.get("actor_id", "player")), ctx)
    if "carry" not in found.get("capabilities", []) or found.get("installed_in"):
        return "something loose that can be taken up"
    if effect.get("other_id") and not (
        person(state, effect["other_id"]) and in_reach(state, ctx, person(state, effect["other_id"]))
    ):
        return "whoever consumes it, within reach"
    return None


@block("write", "information", ("target_id", "text"), "anyone who looks at it reads it in their own call and judges it")
def _check_write(state, effect, ctx):
    """Words written on a surface (chalk on bark, a scratched sign). If it claims to come from someone
    (as_if_from), readers see that claim and judge it for themselves: a forged permit is just writing."""
    if thing(state, ctx, effect["target_id"]) is None:
        return "a surface within reach"
    if len(effect["text"]) > MAX_TEXT or len(effect.get("as_if_from") or "") > 60:
        return f"text of at most {MAX_TEXT} characters"
    return None


alias("mark", "write", "anyone who looks at it sees it in their own call")


@block("touch", "touch", ("target_id",), "the person touched remembers it and decides what it means; onlookers see it")
def _check_touch(state, effect, ctx):
    """A kiss, a hug, a slap, a hand on a shoulder: no change of body by itself (a real blow is harm). A thing can be
    touched too (a hand in the fire: what it does to the hand is hurts_you; live, craft evals)."""
    someone = person(state, effect["target_id"])
    if someone is None:
        return None if thing(state, ctx, effect["target_id"]) is not None else "someone or something within reach"
    if someone is actor(state, ctx) or not in_reach(state, ctx, someone):
        return "someone else within reach"
    return None


@block("gesture", "touch", (), "onlookers see it")
def _check_gesture(state, effect, ctx):
    """A bow, a wave, a rude sign: seen, nothing more."""
    return None


# --- The reducers ------------------------------------------------------------------------------------------------------


def apply(state: State, effects: list[dict], now: int, actor_id: str, repaint) -> None:
    """Carry out checked effects in order. repaint(obj) gives a changed thing a new picture (consequences)."""
    for effect in effects:
        REGISTRY[effect["kind"]].apply(state, effect, now, actor_id, repaint)


def _state_named(someone: dict, name: str) -> dict | None:
    wanted = name.strip().lower()
    return next((s for s in someone.get("states", []) if s["name"].lower() == wanted), None)


def _set_attribute(holder: dict, attribute: dict) -> bool:
    """Put a named fact on a thing or person, replacing one of the same name. Whether anything changed."""
    attributes = holder.setdefault("attributes", [])
    prior = next((a for a in attributes if a["name"] == attribute["name"]), None)
    if prior == attribute:
        return False
    attributes[:] = [a for a in attributes if a["name"] != attribute["name"]]
    attributes.append(dict(attribute))
    return True


@reducer("attribute")
def _apply_attribute(state, effect, now, actor_id, repaint):
    """On a person: kept on them. On a thing (water too): kept on it, and a changed thing gets a new picture."""
    someone = person(state, effect["target_id"])
    if someone is not None:
        _set_attribute(someone, effect["attribute"])
        return
    obj = state["objects"][effect["target_id"]]
    if _set_attribute(obj, effect["attribute"]):
        obj["revision"] = obj.get("revision", 0) + 1
        if "water_source" not in obj.get("capabilities", []):
            repaint(obj)


@reducer("connect", "disconnect")
def _apply_connection(state, effect, now, actor_id, repaint):
    obj, other = state["objects"][effect["target_id"]], state["objects"][effect["other_id"]]
    for first, second in ((obj, other), (other, obj)):
        links = first.setdefault("bound_to", [])
        if effect["kind"] == "connect" and second["id"] not in links:
            links.append(second["id"])
        elif effect["kind"] == "disconnect" and second["id"] in links:
            links.remove(second["id"])
        else:
            continue
        first["revision"] = first.get("revision", 0) + 1


def put_state(someone: dict, name: str, value: str, limits: list, minutes: int, now: int, by: str) -> None:
    """A state on a body, replacing one of the same name."""
    states = someone.setdefault("states", [])
    states[:] = [s for s in states if s["name"].lower() != name.strip().lower()]
    states.append(
        {
            "name": name.strip(),
            "value": (value or "").strip(),
            "limits": list(dict.fromkeys(limits or [])),
            "since": now,
            "until": now + minutes * 60_000 if minutes else None,
            "by": by,
        }
    )


@reducer("condition")
def _apply_condition(state, effect, now, actor_id, repaint):
    someone = person(state, effect["target_id"])
    put_state(
        someone,
        effect["name"],
        effect.get("value"),
        effect.get("limits"),
        int(effect.get("minutes") or 0),
        now,
        actor_id,
    )


@reducer("end_condition")
def _apply_end_condition(state, effect, now, actor_id, repaint):
    someone = person(state, effect["target_id"])
    gone = _state_named(someone, effect["name"])
    someone["states"] = [s for s in someone.get("states", []) if s is not gone]


def _water_in(obj: dict) -> bool:
    return obj.get("water_l", 0.0) > 0 or "water_source" in obj.get("capabilities", [])


def _as_drink(effect: dict, actor_id: str) -> dict:
    amount = effect.get("amount") or tuning.DRINK_SIP_L
    return {
        **effect,
        "kind": "transfer",
        "other_id": effect.get("other_id") or actor_id,
        "relation": "into",
        "amount": amount,
    }


@reducer("consume")
def _apply_consume(state, effect, now, actor_id, repaint):
    if _water_in(state["objects"][effect["target_id"]]):
        _apply_transfer(state, _as_drink(effect, actor_id), now, actor_id, repaint)
        return
    state["objects"][effect["target_id"]].update(holder_id="used", condition="used up")


@reducer("write", "mark")
def _apply_writing(state, effect, now, actor_id, repaint):
    text = effect["text"].strip()
    if effect.get("as_if_from"):
        text += f" (it claims to be from {effect['as_if_from'].strip()})"
    obj = state["objects"][effect["target_id"]]
    written = {
        "name": "writing" if effect["kind"] == "write" else "mark",
        "value": text,
        "status": "observed",
        "basis_ids": [obj["id"]],
    }
    if _set_attribute(obj, written):
        obj["revision"] = obj.get("revision", 0) + 1
        repaint(obj)


# --- Phase 2: place and structure (B), containers and mixtures (C), matter (A) ------------------------------------
# Each block's law and reducer sit together. Where a thing is, what it rests on or is inside, whether it's closed,
# hidden or in the way are fields on the thing; `settle` keeps them true after every step (contents go where their
# container goes, a thing picked up is no longer in the way).

FIXED = ("fixture", "fire", "water")  # Features that stay where the map put them.


def gone(obj: dict | None) -> bool:
    """Used up, made into something else, or destroyed: no longer a thing of its own."""
    holder = str((obj or {}).get("holder_id") or "")
    return obj is None or holder == "used" or holder.startswith(("in:", "into:")) or obj.get("condition") == "destroyed"


def spot(state: State, obj: dict) -> dict:
    """Where a thing is: whoever carries it, the container it's in, or its own cell."""
    holder = obj.get("holder_id")
    if holder == "player":
        return state["player"]
    if holder and (someone := cast.find(state["npcs"], holder)) is not None:
        return someone
    box = state["objects"].get(obj.get("inside") or "")
    return spot(state, box) if box is not None and box is not obj else obj


def contents(state: State, container_id: str) -> list[dict]:
    return [o for o in state["objects"].values() if o.get("inside") == container_id and not gone(o)]


def shut_in(state: State, obj: dict) -> bool:
    """Inside something closed (a sealed jar, a shut chest): out of reach and out of sight."""
    seen = set()
    while obj.get("inside") and obj["inside"] not in seen:
        seen.add(obj["inside"])
        obj = state["objects"].get(obj["inside"]) or {}
        if obj.get("closed"):
            return True
    return False


def unseen_by(obj: dict, viewer_id: str) -> bool:
    """Hidden from this person: everyone but whoever hid it (D-65)."""
    return bool(obj.get("hidden")) and obj["hidden"].get("by") != viewer_id


def _load(state: State, obj: dict) -> float:
    return obj["mass_kg"] + obj.get("water_l", 0.0) + sum(_load(state, c) for c in contents(state, obj["id"]))


def _room(state: State, box: dict) -> float:
    """Litres (about kilograms) still free in a container."""
    return round(
        box.get("capacity_l", 0.0) - box.get("water_l", 0.0) - sum(_load(state, c) for c in contents(state, box["id"])),
        3,
    )


def _strength(ctx: dict) -> float:
    """What the actor can shift along the ground (drag, push, roll), with everyone committed to help."""
    return tuning.MOVE_LIMIT_KG * (1 + len(ctx.get("helpers") or []))


def _carries(state: State, ctx: dict, extra_kg: float) -> bool:
    """Whether the stranger could carry this much more (people in the world aren't weighed)."""
    if ctx.get("actor_id", "player") != "player":
        return True
    import m2

    return m2.inventory_mass(state) + extra_kg <= tuning.CARRY_LIMIT_KG


def _movable(state: State, ctx: dict, obj: dict) -> str | None:
    """The law of shifting a thing: not fitted in place, not part of the land, not in someone else's hands, and no
    heavier than the actor and their helpers can drag."""
    if obj.get("installed_in") or obj.get("condition") == "installed":
        return f"the {obj['name']} is fitted in place: it has to be worked out first"
    if "water_source" in obj.get("capabilities", []) or obj.get("feature") in FIXED:
        return f"the {obj['name']} stays where it is"
    if obj.get("feature") == "tree" and obj.get("condition") == "usable":
        return f"the {obj['name']} is rooted"
    if obj.get("holder_id") not in (None, ctx.get("actor_id", "player")) and not obj.get("on_person"):
        return f"someone is holding the {obj['name']}"
    load = _load(state, obj)
    if load > _strength(ctx):
        more = math.ceil(load / tuning.MOVE_LIMIT_KG) - 1 - len(ctx.get("helpers") or [])
        return f"the {obj['name']} ({load:g} kg) is too heavy to shift without {more} more people helping"
    return None


def _cell(state: State, effect: dict, near: dict, reach: float) -> tuple[int, int] | str:
    """The cell an effect names: open ground, within reach of near. A problem in words otherwise."""
    cell = effect.get("cell") or []
    if len(cell) != 2:
        return "a cell [x, y] to put it"
    x, y = int(cell[0]), int(cell[1])
    if not paths.grid(state).walkable((x, y)):
        return "open ground to put it on"
    if math.dist((x, y), (near["x"], near["y"])) > reach:
        return f"somewhere within {reach:g} cells"
    return (x, y)


def _occupied(state: State, cell: tuple[int, int]) -> bool:
    return any(cast.cell(p) == cell for p in [state["player"], *state["npcs"]] if p.get("alive", True))


def _nearest_open(state: State, centre: tuple[float, float], near: float, test) -> tuple[int, int] | None:
    """The open cell closest to centre, within near of it, that passes test (nearest first, then by x, y)."""
    walkable = paths.grid(state).walkable
    cx, cy = round(centre[0]), round(centre[1])
    span = math.ceil(near)
    cells = [
        (x, y)
        for x in range(cx - span, cx + span + 1)
        for y in range(cy - span, cy + span + 1)
        if math.dist((x, y), centre) <= near and walkable((x, y)) and test((x, y))
    ]
    return min(cells, key=lambda c: (math.dist(c, centre), c)) if cells else None


def _destination(state: State, effect: dict, ctx: dict, obj: dict) -> str | None:
    """Where a moved thing ends up: the cell given, or the open cell nearest to other_id (dragged to the gate,
    rolled up against the trough). The law fixes the cell in the effect, so it lands where it was checked."""
    start = spot(state, obj)
    if effect.get("cell"):
        cell = _cell(state, effect, start, tuning.MOVE_CELLS)
        if isinstance(cell, str):
            return cell
    elif effect.get("other_id"):
        there = person(state, effect["other_id"]) or state["objects"].get(effect["other_id"])
        if there is None or there is obj:
            return "somewhere to put it"
        at = cast.nearest(there, start) if there.get("area") else (spot(state, there)["x"], spot(state, there)["y"])
        cell = _nearest_open(
            state,
            at,
            2.5,
            lambda c: math.dist(c, (start["x"], start["y"])) <= tuning.MOVE_CELLS and not _occupied(state, c),
        )
        if cell is None:
            return f"open ground beside it within {tuning.MOVE_CELLS:g} cells"
    elif effect["kind"] == "block":  # Rolled or tipped over where it lies (the judge can't see where the path runs).
        cell = (int(start["x"]), int(start["y"]))
    else:
        return "where it goes: a cell, or something to put it beside"
    if effect["kind"] == "block" and _occupied(state, cell):
        return "a cell nobody is standing on"
    effect["cell"] = [cell[0], cell[1]]
    return None


def _loose(obj: dict, **where) -> None:
    """A thing set down somewhere new: nothing it was in, on, hidden in or blocking still holds."""
    obj.update(
        {"holder_id": None, "inside": None, "rests_on": None, "placed": None, "blocks": False, "hidden": None, **where}
    )
    obj["revision"] = obj.get("revision", 0) + 1


def _available(ctx: dict, thing_id: str | None) -> dict | None:
    return ctx["available"].get(thing_id or "")


@block("move", "place", ("target_id",), "where it is: the judge's view, people's paths, inspect")
def _check_move(state, effect, ctx):
    """Push, drag, roll or carry a thing to a cell nearby, or up beside something (other_id): a log rolled off the
    road, a crate dragged under the bracket. Strength: what the actor and committed helpers can shift; the place
    must be open ground."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    return _movable(state, ctx, obj) or _destination(state, effect, ctx, obj)


@reducer("move")
def _apply_move(state, effect, now, actor_id, repaint):
    _loose(state["objects"][effect["target_id"]], x=int(effect["cell"][0]), y=int(effect["cell"][1]))


@block("block", "place", ("target_id",), "nobody walks through that cell: the stranger, people on their rounds")
def _check_block(state, effect, ctx):
    """Put something big across a way (a cart in the lane, the log rolled across the road): it ends at the cell
    given or beside other_id, and that cell can't be walked through until it's moved."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    if obj["mass_kg"] < tuning.BLOCK_MIN_KG and (obj.get("length_m") or 0) < 1.5:
        return f"something bigger than the {obj['name']} to stand in anyone's way"
    return _movable(state, ctx, obj) or _destination(state, effect, ctx, obj)


@reducer("block")
def _apply_block(state, effect, now, actor_id, repaint):
    _loose(state["objects"][effect["target_id"]], x=int(effect["cell"][0]), y=int(effect["cell"][1]), blocks=True)


def _bears(state: State, under: dict, obj: dict) -> str | None:
    """Whether one thing can bear another resting on it."""
    if under.get("holder_id") is not None:
        return f"the {under['name']} has to be set down first"
    if not {"rigid", "stable_support"} & set(under.get("flags", [])) and "water_source" not in under.get(
        "capabilities", []
    ):
        return f"the {under['name']} can't bear anything"
    rated = under.get("rated_load_kg")
    if rated and _load(state, obj) > rated:
        return f"the {under['name']} bears only {rated:g} kg"
    return None


@block(
    "place", "place", ("target_id", "other_id", "relation"), "the judge's view (what's on, under or by what), inspect"
)
def _check_place(state, effect, ctx):
    """Set a thing on, under or beside another thing, or beside a person (a stone under the log, the bowl on the
    trestles). Into a container is put_in; propped against something is support."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    if effect["relation"] not in ("on", "under", "beside"):
        return "on, under or beside"
    problem = _movable(state, ctx, obj)
    if problem:
        return problem
    found = target(state, ctx, effect["other_id"])
    if found is None or found[1] is obj:
        return "something else within reach to put it by"
    kind, there = found
    if kind == "person":
        return None if effect["relation"] == "beside" else "beside a person, not on or under them"
    if effect["relation"] == "on":
        return _bears(state, there, obj)
    if effect["relation"] == "under" and _load(state, there) > _strength(ctx) and not there.get("rests_on"):
        return f"the {there['name']} has to be lifted to get anything under it"
    return None


@reducer("place")
def _apply_place(state, effect, now, actor_id, repaint):
    there = person(state, effect["other_id"]) or state["objects"][effect["other_id"]]
    where = spot(state, there) if "x" not in there or there.get("holder_id") else there
    _loose(
        state["objects"][effect["target_id"]],
        x=where["x"],
        y=where["y"],
        placed={"relation": effect["relation"], "other_id": effect["other_id"]},
        rests_on=effect["other_id"] if effect["relation"] == "on" else None,
    )


@block(
    "support",
    "place",
    ("target_id",),
    "the judge (what's propped where: climbing, reaching); it falls when what holds it is moved",
)
def _check_support(state, effect, ctx):
    """Rest one thing on or against another so it bears it: a plank across the trestles (other_id), a ladder against
    a wall or a tree (cell: the open cell beside it, where the foot stands)."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    problem = _movable(state, ctx, obj)
    if problem:
        return problem
    if effect.get("other_id"):
        under = thing(state, ctx, effect["other_id"])
        if under is None or under is obj:
            return "something else within reach to rest it on"
        return _bears(state, under, obj)
    walkable = paths.grid(state).walkable

    def against(c):
        return not all(walkable((c[0] + dx, c[1] + dy)) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    me = actor(state, ctx)
    if effect.get("cell"):
        cell = _cell(state, effect, me, tuning.REACH_CELLS + 1)
        if isinstance(cell, str):
            return cell
    else:  # The nearest wall, tree or rock to the actor.
        cell = _nearest_open(state, (me["x"], me["y"]), tuning.REACH_CELLS + 1, against)
        if cell is None:
            return "a wall, a tree or a rock within reach to lean it against"
    if not against(cell):
        return "a wall, a tree or a rock beside that cell to lean it against"
    effect["cell"] = [cell[0], cell[1]]
    return None


@reducer("support")
def _apply_support(state, effect, now, actor_id, repaint):
    if effect.get("other_id"):
        under = state["objects"][effect["other_id"]]
        _loose(state["objects"][effect["target_id"]], x=under["x"], y=under["y"], rests_on=under["id"])
    else:
        x, y = int(effect["cell"][0]), int(effect["cell"][1])
        _loose(state["objects"][effect["target_id"]], x=x, y=y, rests_on="wall")
    if effect.get("value"):
        state["objects"][effect["target_id"]]["placed"] = {
            "relation": "against",
            "other_id": effect.get("other_id"),
            "how": effect["value"][:120],
        }


@block("open", "place", ("target_id",), "what's inside can be reached and seen; a broken seal shows")
def _check_open(state, effect, ctx):
    """Open a lid, a sack's neck, a jar, a chest. A sealed thing opens by breaking its seal, and that shows."""
    obj = _available(ctx, effect["target_id"])
    return None if obj is not None else "a thing within reach"  # Already open: nothing to do, no harm (live: honey).


@reducer("open")
def _apply_open(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    if obj.get("sealed"):
        _set_attribute(
            obj, {"name": "seal", "value": "the seal is broken", "status": "observed", "basis_ids": [obj["id"]]}
        )
        obj["attributes"] = [a for a in obj["attributes"] if a["name"] != "sealed"]
    obj.update(closed=False, sealed=False)
    obj["revision"] = obj.get("revision", 0) + 1


@block("close", "place", ("target_id",), "what's inside is out of reach and out of sight")
def _check_close(state, effect, ctx):
    """Shut a lid, tie a sack's neck, stopper a jar."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    if "container" not in obj.get("flags", []):
        return f"the {obj['name']} has no opening to close"
    return None


@reducer("close")
def _apply_close(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    obj["closed"] = True
    obj["revision"] = obj.get("revision", 0) + 1


@block(
    "hide", "place", ("target_id",), "nobody but whoever hid it sees it (their own calls, the judge); found when moved"
)
def _check_hide(state, effect, ctx):
    """Hide a thing under or in something (other_id: the knife under the straw), or a small thing by itself (tucked
    into clothes, pushed into the grass). value: where, in words."""
    obj = _available(ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    if "carry" not in obj.get("capabilities", []) or obj.get("installed_in"):
        return f"the {obj['name']} is too big to hide"
    if obj.get("holder_id") not in (None, ctx.get("actor_id", "player")) and not obj.get("on_person"):
        return f"someone is holding the {obj['name']}"
    if effect.get("other_id"):
        cover = thing(state, ctx, effect["other_id"])
        if cover is None or cover is obj:
            return "something within reach to hide it under or in"
        return None
    if obj["mass_kg"] > tuning.HIDE_LOOSE_KG:
        return f"something to hide the {obj['name']} under: only small things tuck away by themselves"
    return None


@reducer("hide")
def _apply_hide(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    cover = state["objects"].get(effect.get("other_id") or "")
    where = (effect.get("value") or "").strip()[:120]
    if cover is not None and cover["name"] not in where:  # "under" alone says nothing: under what.
        where = f"{where or 'under'} the {cover['name']}"
    where = where or "out of sight"
    if cover is None and obj.get("holder_id") == actor_id:  # Concealed on the body: still carried.
        obj["hidden"] = {"by": actor_id, "where": where, "holder": actor_id}
        return
    at = spot(state, cover) if cover is not None else spot(state, obj)
    _loose(obj, x=at["x"], y=at["y"])
    obj["hidden"] = {"by": actor_id, "where": where, "holder": None}


@block(
    "put_in",
    "containers",
    ("target_id", "other_id"),
    "contents on inspect and in the judge's view; they go where it goes; out of reach while it's closed",
)
def _check_put_in(state, effect, ctx):
    """Put a solid thing into a container (stones in the bucket, the knife in the crate)."""
    obj, box = _available(ctx, effect["target_id"]), _available(ctx, effect["other_id"])
    if obj is None or box is None or obj is box:
        return "a thing and a container, both within reach"
    if "carry" not in obj.get("capabilities", []) or obj.get("installed_in"):
        return f"the {obj['name']} can't be lifted in"
    if obj.get("holder_id") not in (None, ctx.get("actor_id", "player")) and not obj.get("on_person"):
        return f"someone is holding the {obj['name']}"
    if "container" not in box.get("flags", []) or not box.get("capacity_l"):
        return f"the {box['name']} can't hold things"
    if box.get("closed"):
        return f"the {box['name']} is closed"
    inner = box
    while inner.get("inside"):
        if inner["inside"] == obj["id"]:
            return "a thing can't go inside what it holds"
        inner = state["objects"].get(inner["inside"]) or {}
    if _load(state, obj) > _room(state, box):
        return f"the {box['name']} hasn't room for the {obj['name']}"
    if box.get("holder_id") == ctx.get("actor_id", "player") and obj.get("holder_id") != box.get("holder_id"):
        if not _carries(state, ctx, _load(state, obj)):
            return "more than you can carry"
    return None


@reducer("put_in")
def _apply_put_in(state, effect, now, actor_id, repaint):
    obj, box = state["objects"][effect["target_id"]], state["objects"][effect["other_id"]]
    at = spot(state, box)
    _loose(obj, x=at["x"], y=at["y"], inside=box["id"])
    obj["holder_id"] = box.get("holder_id")


@block("take_out", "containers", ("target_id",), "it's in the actor's hands")
def _check_take_out(state, effect, ctx):
    """Take a thing out of the container it's in."""
    obj = state["objects"].get(effect["target_id"])
    if obj is None or gone(obj) or not obj.get("inside"):
        return "a thing inside a container"
    box = _available(ctx, obj["inside"])
    if box is None:
        return "its container within reach"
    if box.get("closed") or shut_in(state, box):
        return f"the {box['name']} is closed"
    if obj.get("holder_id") != ctx.get("actor_id", "player") and not _carries(state, ctx, _load(state, obj)):
        return "more than you can carry"
    return None


@reducer("take_out")
def _apply_take_out(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    _loose(obj)
    obj["holder_id"] = actor_id


def _litres(effect: dict, have: float) -> float:
    amount = float(effect.get("amount") or 0)
    return round(min(have, amount) if amount > 0 else have, 3)


def mixture_words(obj: dict) -> str:
    return "; ".join(f"{m['name']}: {m['value']}" for m in obj.get("mixture") or [])


def _mixed(into: dict, notes: list[dict]) -> None:
    mixture = into.setdefault("mixture", [])
    for note in notes:
        if note not in mixture:
            mixture.append(dict(note))
    del mixture[: max(0, len(mixture) - 8)]


def _drained(obj: dict) -> None:
    """A container emptied: what was in the water went with it; an empty pot is cold."""
    if obj.get("water_l", 0.0) <= 0 and "water_source" not in obj.get("capabilities", []):
        obj.update(water_l=0.0, mixture=[], temperature="cold")


@block(
    "transfer",
    "containers",
    ("target_id",),
    "where it goes: another container, a soaked or wet body or thing, someone who drank it, or the ground",
)
def _check_transfer(state, effect, ctx):
    """Liquid poured or tipped from a container or water source (target_id) into another container (other_id),
    over a person or thing (relation over), down someone's throat (relation into), or out on the ground (no
    other_id). amount in litres; none: all of it. Liquid is conserved: what leaves one place arrives in another or
    soaks into the ground."""
    source = thing(state, ctx, effect["target_id"])
    if source is None:
        return "a container or water source within reach"
    if source.get("closed"):
        return f"the {source['name']} is closed"
    if _poured_stuff(state, effect):
        return _check_mix(state, _as_mix(effect), ctx)
    have = source.get("water_l", 0.0)
    if have <= 0:
        return f"the {source['name']} is empty"
    litres = _litres(effect, have)
    if float(effect.get("amount") or 0) > have + 0.001:
        return f"only {have:g} L in the {source['name']}"
    if not effect.get("other_id"):
        return None
    found = target(state, ctx, effect["other_id"])
    if found is None:
        return "where it goes, within reach"
    kind, there = found
    if kind == "person":
        if effect.get("relation") == "into" and litres > tuning.DRINK_MAX_L:
            return f"nobody drinks more than {tuning.DRINK_MAX_L:g} L at once"
        return None
    if there is source:
        return "somewhere else to pour it"
    if there.get("closed"):
        return f"the {there['name']} is closed"
    if effect.get("relation") != "over" and there.get("holder_id") == ctx.get("actor_id", "player"):
        if source.get("holder_id") != there["holder_id"] and not _carries(
            state, ctx, min(litres, max(0, _room(state, there)))
        ):
            return "more than you can carry"
    return None


def _poured_stuff(state: State, effect: dict) -> bool:
    """Honey, oil or flour tipped from its pot into a container (live: the judge poured honey with transfer): the
    world's only liquid is water, so what a thing holds as its own mass goes in as a mix."""
    source = state["objects"].get(effect["target_id"]) or {}
    into = state["objects"].get(effect.get("other_id") or "") or {}
    return (
        not source.get("water_l")
        and "container" not in source.get("flags", [])  # An empty bucket has nothing to pour.
        and "water_source" not in source.get("capabilities", [])
        and "container" in into.get("flags", [])
        and effect.get("relation") != "over"
    )


def _as_mix(effect: dict) -> dict:
    return {**effect, "kind": "mix", "target_id": effect["other_id"], "other_id": effect["target_id"]}


@reducer("transfer")
def _apply_transfer(state, effect, now, actor_id, repaint):
    if _poured_stuff(state, effect):
        _apply_mix(state, _as_mix(effect), now, actor_id, repaint)
        return
    source = state["objects"][effect["target_id"]]
    litres = _litres(effect, source.get("water_l", 0.0))
    notes = [dict(m) for m in source.get("mixture") or []]
    what = "water" + (f" ({mixture_words(source)})" if notes else "")
    source["water_l"] = round(source.get("water_l", 0.0) - litres, 3)
    _drained(source)
    spilled = litres
    someone = person(state, effect.get("other_id"))
    there = state["objects"].get(effect.get("other_id") or "")
    if someone is not None:
        if effect.get("relation") == "into":
            put_state(someone, "drank", f"{litres:g} L of {what}", [], tuning.DRANK_MINUTES, now, actor_id)
            spilled = 0.0
        elif litres >= tuning.SOAK_MIN_L:
            put_state(someone, "soaked", f"soaked with {what}", [], tuning.SOAKED_MINUTES, now, actor_id)
    elif there is not None:
        if "water_source" in there.get("capabilities", []):
            there["water_l"] = round(there["water_l"] + litres, 3)
            _mixed(there, notes)
            spilled = 0.0
        elif "container" in there.get("flags", []) and there.get("capacity_l") and effect.get("relation") != "over":
            poured = max(0.0, min(litres, _room(state, there)))
            there["water_l"] = round(there.get("water_l", 0.0) + poured, 3)
            _mixed(there, notes)
            spilled = round(litres - poured, 3)
        else:
            _set_attribute(
                there, {"name": "wet", "value": f"wet with {what}", "status": "observed", "basis_ids": [source["id"]]}
            )
        there["revision"] = there.get("revision", 0) + 1
    if spilled > 0:
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + spilled, 3)


@block(
    "mix",
    "containers",
    ("target_id", "other_id"),
    "whoever drinks or uses it reads what's in it; the judge; the ingredient is gone into it",
)
def _check_mix(state, effect, ctx):
    """Stir an ingredient (other_id) into what a container holds (honey into water, ash into fat, herbs steeped).
    value: what it becomes; amount: kilograms of the ingredient used (none: all of it). Two liquids: transfer."""
    box, ingredient = _available(ctx, effect["target_id"]), _available(ctx, effect["other_id"])
    if box is None or ingredient is None or box is ingredient:
        return "a container and something to mix in, both within reach"
    if "container" not in box.get("flags", []) and "container" in ingredient.get("flags", []):
        # Named the other way round (live: honey into the bucket, the honey first): the container is plain.
        effect["target_id"], effect["other_id"] = effect["other_id"], effect["target_id"]
        box, ingredient = ingredient, box
    if "container" not in box.get("flags", []):
        return f"the {box['name']} can't hold a mixture"
    if box.get("closed"):
        return f"the {box['name']} is closed"
    if "carry" not in ingredient.get("capabilities", []) or ingredient.get("installed_in"):
        return f"the {ingredient['name']} can't go in"
    if ingredient.get("holder_id") not in (None, ctx.get("actor_id", "player")) and not ingredient.get("on_person"):
        return f"someone is holding the {ingredient['name']}"
    if ingredient.get("water_l", 0.0) > 0:
        return "pour one liquid into another with transfer"
    used = min(ingredient["mass_kg"], float(effect.get("amount") or 0) or ingredient["mass_kg"])
    if box.get("capacity_l") and used > _room(state, box) + box.get("water_l", 0.0) + 0.001:
        return f"the {box['name']} hasn't room for it"  # A full pot spills a little; it can't take more than it holds.
    return None


@reducer("mix")
def _apply_mix(state, effect, now, actor_id, repaint):
    box, ingredient = state["objects"][effect["target_id"]], state["objects"][effect["other_id"]]
    used = round(min(ingredient["mass_kg"], float(effect.get("amount") or 0) or ingredient["mass_kg"]), 3)
    over = round(used - _room(state, box), 3) if box.get("capacity_l") else 0.0
    if over > 0 and box.get("water_l", 0.0) > 0:  # Stirred into a full bucket: a little water slops over the brim.
        spilled = min(over, box["water_l"])
        box["water_l"] = round(box["water_l"] - spilled, 3)
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + spilled, 3)
    _mixed(box, [{"name": ingredient["name"], "value": (effect.get("value") or "mixed in").strip()[:160]}])
    box["mass_kg"] = round(box["mass_kg"] + used, 3)
    box["revision"] = box.get("revision", 0) + 1
    if used >= ingredient["mass_kg"] - 0.001:
        ingredient.update(holder_id=f"in:{box['id']}", condition="used up")
    else:
        ingredient["mass_kg"] = round(ingredient["mass_kg"] - used, 3)


@block(
    "contaminate",
    "containers",
    ("target_id", "value"),
    "whoever drinks or uses it (in their own call); the judge; not plain to see",
)
def _check_contaminate(state, effect, ctx):
    """Foul water, food or a thing (piss in the trough, dirt in the honey, dung on a blade). value: with what.
    other_id: what fouls it, within reach; none: the actor's own body."""
    found = thing(state, ctx, effect["target_id"])
    if found is None:
        return "a thing or water within reach"
    if found.get("sealed") or shut_in(state, found):
        return f"the {found['name']} is sealed"
    if effect.get("other_id") and effect["other_id"] != ctx.get("actor_id", "player"):
        if thing(state, ctx, effect["other_id"]) is None:
            return "what fouls it, within reach"
    if len(effect["value"]) > 200:
        return "a description of at most 200 characters"
    return None


@reducer("contaminate")
def _apply_contaminate(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    note = {"name": "fouled", "value": effect["value"].strip()}
    if obj.get("water_l", 0.0) > 0 or "water_source" in obj.get("capabilities", []):
        _mixed(obj, [note])
    else:
        _set_attribute(obj, {**note, "status": "observed", "basis_ids": [effect.get("other_id") or obj["id"]]})
    obj["revision"] = obj.get("revision", 0) + 1


@block(
    "soak",
    "containers",
    ("target_id", "other_id"),
    "the judge (a wet thing burns poorly, a wet cloth cools); inspect; it's heavier",
)
def _check_soak(state, effect, ctx):
    """Soak or dip a thing (target_id) in water from a container or water source (other_id): a rag in the bucket,
    a cloak in the trough. amount: litres it takes up (none: about a cup)."""
    obj, source = _available(ctx, effect["target_id"]), thing(state, ctx, effect["other_id"])
    if obj is None or source is None or obj is source:
        return "a thing and water, both within reach"
    if source.get("closed"):
        return f"the {source['name']} is closed"
    litres = float(effect.get("amount") or tuning.SOAK_DEFAULT_L)
    if source.get("water_l", 0.0) < litres:
        return f"not enough water in the {source['name']}"
    if obj.get("holder_id") == ctx.get("actor_id", "player") and not _carries(state, ctx, litres):
        return "more than you can carry"
    return None


@reducer("soak")
def _apply_soak(state, effect, now, actor_id, repaint):
    obj, source = state["objects"][effect["target_id"]], state["objects"][effect["other_id"]]
    litres = round(float(effect.get("amount") or tuning.SOAK_DEFAULT_L), 3)
    source["water_l"] = round(source["water_l"] - litres, 3)
    what = "water" + (f" ({mixture_words(source)})" if source.get("mixture") else "")
    _drained(source)
    obj["mass_kg"] = round(obj["mass_kg"] + litres, 3)  # The water is in it now.
    obj["absorbed_l"] = round(obj.get("absorbed_l", 0.0) + litres, 3)
    _set_attribute(
        obj,
        {
            "name": "wet",
            "value": (effect.get("value") or f"soaked in {what}").strip()[:200],
            "status": "observed",
            "basis_ids": [source["id"]],
        },
    )
    obj["revision"] = obj.get("revision", 0) + 1
    repaint(obj)


@block(
    "seal",
    "containers",
    ("target_id", "other_id"),
    "nothing gets in or out: its contents can't be reached or fouled; opening it breaks the seal, and that shows",
)
def _check_seal(state, effect, ctx):
    """Seal a container shut with something (other_id: resin, clay, wax, a stopper and cord), used up in the seal."""
    box, sealant = _available(ctx, effect["target_id"]), _available(ctx, effect["other_id"])
    if box is None or sealant is None or box is sealant:
        return "a container and something to seal it with, both within reach"
    if "container" not in box.get("flags", []):
        return f"the {box['name']} has no opening to seal"
    if box.get("sealed"):
        return f"the {box['name']} is already sealed"
    if "carry" not in sealant.get("capabilities", []) or sealant["mass_kg"] > tuning.SEALANT_MAX_KG:
        return f"the {sealant['name']} is too big to seal it with"
    return None


@reducer("seal")
def _apply_seal(state, effect, now, actor_id, repaint):
    box, sealant = state["objects"][effect["target_id"]], state["objects"][effect["other_id"]]
    box.update(closed=True, sealed=True)
    box["attributes"] = [a for a in box.get("attributes", []) if a["name"] != "seal"]
    how = (effect.get("value") or f"sealed with the {sealant['name']}").strip()[:160]
    _set_attribute(box, {"name": "sealed", "value": how, "status": "observed", "basis_ids": [sealant["id"]]})
    sealant.update(holder_id=f"in:{box['id']}", condition="used up")
    box["revision"] = box.get("revision", 0) + 1
    repaint(box)


def _breakable(state: State, ctx: dict, obj: dict | None, what: str) -> str | None:
    """A thing an effect can break or harm: within reach, not part of the gate's working (lift it out first), and
    something heavy needs a tool or helpers."""
    if obj is None:
        return "a thing within reach"
    if obj.get("installed_in") or obj.get("feature") == "fixture":
        return f"the {obj['name']} is fitted in place: it has to be worked out first"
    if obj.get("holder_id") not in (None, ctx.get("actor_id", "player")) and not obj.get("on_person"):
        return f"someone is holding the {obj['name']}"
    tool = thing(state, ctx, ctx.get("other_id"))
    if obj["mass_kg"] > tuning.CARRY_LIMIT_KG and tool is None and not ctx.get("helpers"):
        return f"something to {what} the {obj['name']} with"
    return None


@block(
    "damage", "matter", ("target_id", "name"), "inspect and the judge (what it can no longer do); onlookers; its owner"
)
def _check_damage(state, effect, ctx):
    """Harm a thing without destroying it: cracked, torn, blunted, holed, bent. name: what it looks like now; flags:
    the qualities it loses (a holed bucket stops being a container and watertight, a blunted knife loses
    sharp_edge). other_id: what did it."""
    obj = thing(state, ctx, effect["target_id"])
    if obj is not None and obj.get("installed_in"):
        obj = dict(obj, installed_in=None)  # A fitted thing can still be cracked where it is.
    problem = _breakable(state, {**ctx, "other_id": effect.get("other_id")}, obj, "damage")
    if problem:
        return problem
    lost = [f for f in effect.get("flags") or [] if f not in obj.get("flags", [])]
    if lost:
        return f"the {obj['name']} isn't {', '.join(lost)} to begin with"
    return _named(effect["name"], set(), 60)


@reducer("damage")
def _apply_damage(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    lost = [f for f in effect.get("flags") or [] if f in obj.get("flags", [])]
    obj["flags"] = [f for f in obj.get("flags", []) if f not in lost]
    record = obj.setdefault("damage", {"lost_flags": [], "capacity_l": obj.get("capacity_l", 0.0)})
    record["lost_flags"] = list(dict.fromkeys(record["lost_flags"] + lost))
    basis = [i for i in (effect.get("other_id"), obj["id"]) if i]
    _set_attribute(
        obj,
        {
            "name": "damaged",
            "value": (effect["name"] + (f": {effect['value']}" if effect.get("value") else "")).strip()[:200],
            "status": "observed",
            "basis_ids": basis,
        },
    )
    if {"container", "watertight"} & set(lost) and obj.get("water_l", 0.0) > 0:  # It leaks: the water runs out.
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + obj["water_l"], 3)
        obj["water_l"] = 0.0
        _drained(obj)
    if "container" in lost:
        obj["capacity_l"] = 0.0
        for inner in contents(state, obj["id"]):  # They fall out.
            at = spot(state, obj)
            _loose(inner, x=at["x"], y=at["y"])
    obj["revision"] = obj.get("revision", 0) + 1
    if "water_source" not in obj.get("capabilities", []):
        repaint(obj)


@block("repair", "matter", ("target_id",), "inspect and the judge (what it can do again)")
def _check_repair(state, effect, ctx):
    """Mend a damaged thing: a crack sealed with resin, a tear stitched. flags: the lost qualities it gets back
    (only ones it lost; anything new is a make). other_id: what mends it, within reach."""
    obj = thing(state, ctx, effect["target_id"])
    if obj is None:
        return "a thing within reach"
    record = obj.get("damage")
    if not record:
        return f"the {obj['name']} isn't damaged"
    back = [f for f in effect.get("flags") or [] if f not in record["lost_flags"]]
    if back:
        return f"the {obj['name']} never had {', '.join(back)} to get back: that would be making something new"
    if effect.get("other_id") and thing(state, ctx, effect["other_id"]) is None:
        return "what mends it, within reach"
    return None


@reducer("repair")
def _apply_repair(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    record = obj["damage"]
    back = [f for f in effect.get("flags") or [] if f in record["lost_flags"]] or list(record["lost_flags"])
    obj["flags"] = list(dict.fromkeys(obj.get("flags", []) + back))
    record["lost_flags"] = [f for f in record["lost_flags"] if f not in back]
    if "container" in back:
        obj["capacity_l"] = record.get("capacity_l", 0.0)
    if not record["lost_flags"]:
        obj["damage"] = None  # Never deleted: a saved world merges object fields.
        obj["attributes"] = [a for a in obj.get("attributes", []) if a["name"] != "damaged"]
    how = (effect.get("value") or "mended").strip()[:200]
    _set_attribute(
        obj,
        {
            "name": "mended",
            "value": how,
            "status": "observed",
            "basis_ids": [i for i in (effect.get("other_id"), obj["id"]) if i],
        },
    )
    obj["revision"] = obj.get("revision", 0) + 1
    repaint(obj)


@block(
    "destroy", "matter", ("target_id",), "it's gone from use; whatever was in it or on it falls; its owner; onlookers"
)
def _check_destroy(state, effect, ctx):
    """Smash, tear apart or ruin a thing for good (a pot smashed, a crate kicked to pieces). Breaking it into usable
    pieces is transform; burning is fire. other_id: what did it."""
    obj = thing(state, ctx, effect["target_id"])
    if obj is not None and ("water_source" in obj.get("capabilities", []) or obj.get("feature") in ("fire", "water")):
        return f"the {obj['name']} can't simply be destroyed"
    return _breakable(state, {**ctx, "other_id": effect.get("other_id")}, obj, "break")


@reducer("destroy")
def _apply_destroy(state, effect, now, actor_id, repaint):
    obj = state["objects"][effect["target_id"]]
    at = spot(state, obj)
    for inner in contents(state, obj["id"]):
        _loose(inner, x=at["x"], y=at["y"])
    if obj.get("water_l", 0.0) > 0:
        state["water_spilled_l"] = round(state.get("water_spilled_l", 0.0) + obj["water_l"], 3)
    _loose(obj, x=at["x"], y=at["y"])
    obj.update(condition="destroyed", water_l=0.0, destroyed_by=actor_id)
    _set_attribute(
        obj,
        {
            "name": "destroyed",
            "value": (effect.get("value") or "wrecked").strip()[:200],
            "status": "observed",
            "basis_ids": [obj["id"]],
        },
    )


def settle(state: State) -> None:
    """Things follow what holds them, after every step (D-65): contents go where their container goes and fall out
    when it's gone; something resting on a thing falls when that thing is moved; a thing picked up is no longer in
    anyone's way, propped anywhere, or hidden."""
    objects = state["objects"]
    for _ in range(2):  # A pot in a crate in a cart: twice settles two levels.
        for obj in objects.values():
            if gone(obj):
                if obj.get("inside") or obj.get("blocks"):
                    obj.update(inside=None, blocks=False)
                continue
            box = objects.get(obj.get("inside") or "")
            if obj.get("inside") and (gone(box) or "container" not in box.get("flags", [])):
                at = spot(state, box) if box is not None else obj
                _loose(obj, x=at["x"], y=at["y"])
            elif box is not None:
                obj["holder_id"] = box.get("holder_id")
                if box.get("holder_id") is None:
                    obj.update(x=box["x"], y=box["y"])
            if obj.get("holder_id") is not None and (obj.get("blocks") or obj.get("rests_on") or obj.get("placed")):
                obj.update(blocks=False, rests_on=None, placed=None)
            under = objects.get(obj.get("rests_on") or "")
            if under is not None and (
                gone(under) or under.get("holder_id") is not None or (under["x"], under["y"]) != (obj["x"], obj["y"])
            ):
                obj["rests_on"] = None  # What held it moved away: it falls.
            hidden = obj.get("hidden")
            if hidden and obj.get("holder_id") != hidden.get("holder"):
                obj["hidden"] = None  # Picked up or moved: found.


def plain_to_see(obj: dict) -> list[str]:
    """What anyone looking at a thing can make out besides writing: damage, a broken seal, wet, in the way."""
    lines = [
        f"the {obj['name']}: {a['value']}"
        for a in obj.get("attributes", [])
        if a["name"] in ("damaged", "destroyed", "wet", "seal", "sealed", "mended")
    ]
    if obj.get("blocks"):
        lines.append(f"the {obj['name']} lies across the way")
    if obj.get("rests_on") == "wall":
        lines.append(f"the {obj['name']} is propped against the wall")
    return lines


# --- Consumers: what states stop, and when they end ---------------------------------------------------------------------


def limited(someone: dict | None, limit: str) -> dict | None:
    """The state that stops this person doing this (move, see, speak, hands), if any."""
    for each in (someone or {}).get("states", []):
        if limit in each.get("limits", []):
            return each
    return None


def expire(state: State, now: int) -> list[str]:
    """States whose time is up end (a soaking dries, a drunk sobers). Returns who changed."""
    changed = []
    for someone in [state["player"], *state["npcs"]]:
        states = someone.get("states") or []
        kept = [s for s in states if not s.get("until") or s["until"] > now]
        if len(kept) != len(states):
            someone["states"] = kept
            changed.append(someone.get("id", "player"))
    return changed


def how_they_are(someone: dict) -> list[str]:
    """Their own states and attributes, in words, for their own call (and the judge's view of them)."""
    lines = []
    for each in someone.get("states", []):
        stops = ", ".join(
            {"move": "walking", "see": "seeing", "speak": "speaking", "hands": "using hands"}[x]
            for x in each.get("limits", [])
        )
        lines.append(
            f"{each['name']}"
            + (f": {each['value']}" if each.get("value") else "")
            + (f" (stops {stops})" if stops else "")
        )
    lines += [f"{a['name']}: {a['value']}" for a in someone.get("attributes", [])]
    return lines


def readable(obj: dict) -> list[str]:
    """Writing and marks on a thing, as anyone looking at it can see them."""
    return [
        f"{a['name']} on the {obj['name']}: {a['value']}"
        for a in obj.get("attributes", [])
        if a["name"] in ("writing", "mark")
    ]
