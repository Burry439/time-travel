"""The world's vocabulary (D-65): general building blocks the judge composes for any deed.

Each block works on anything and anyone it makes sense for (things, people including the stranger, water), and
has three parts: a law in code (`check`: reach, strength, conservation, protected names, bounded values), a
reducer (`apply`: what changes in the world), and a consumer (`noticed_by`: who or what reads the change, so it
matters). The open-ended part is data the AI supplies: the names and values of marks and states, the text of
writing, what a state stops someone doing. Models read them back (the judge, each person's own call); code never
lets an effect write into anyone's mind. A block isn't done until all three parts exist, and the content test
holds every registered kind to that.

Families (GDD D-65): F bodies, H information, J touch and gesture, and the open attribute are built here first;
place and structure, containers and mixtures, matter, signals, terrain, fire and processes follow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cast
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
    """Something eaten, drunk, burnt up or otherwise used up. What it does to a body is a condition beside it."""
    found = thing(state, ctx, effect["target_id"])
    if found is None:
        return "the thing within reach"
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
    """A kiss, a hug, a slap, a hand on a shoulder: no change of body by itself (a real blow is harm)."""
    someone = person(state, effect["target_id"])
    if someone is None or someone is actor(state, ctx) or not in_reach(state, ctx, someone):
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


@reducer("condition")
def _apply_condition(state, effect, now, actor_id, repaint):
    someone = person(state, effect["target_id"])
    states = someone.setdefault("states", [])
    states[:] = [s for s in states if s["name"].lower() != effect["name"].strip().lower()]
    minutes = int(effect.get("minutes") or 0)
    states.append(
        {
            "name": effect["name"].strip(),
            "value": (effect.get("value") or "").strip(),
            "limits": list(dict.fromkeys(effect.get("limits") or [])),
            "since": now,
            "until": now + minutes * 60_000 if minutes else None,
            "by": actor_id,
        }
    )


@reducer("end_condition")
def _apply_end_condition(state, effect, now, actor_id, repaint):
    someone = person(state, effect["target_id"])
    gone = _state_named(someone, effect["name"])
    someone["states"] = [s for s in someone.get("states", []) if s is not gone]


@reducer("consume")
def _apply_consume(state, effect, now, actor_id, repaint):
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
