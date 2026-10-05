"""Authored story milestones and private secrets. Milestones observe committed world facts; reaching one does not
freeze later consequences. Secrets are available only from their owner's context and are revealed when that person
chooses to confide.

An outcome reaches each person with the knowledge of it (D-63): who knows is worked out from what they hold
themselves (they saw the gift, watched the beam go up, were told the secret, were in the conversation, or were
brought the news later by someone who was). The outcome's authored reaction for that person (Tomas won't forgive
it, Oren owes you) waits until then, and so does the fact in their own context. A story move someone agrees to can
send them to tell the person it concerns (a move's "tells")."""

from __future__ import annotations

import cast
import content
import evidence
import paths
import persona
import reputation
import rules
import tuning
from shapes import Npc, State, Thing

DATA = content.read("content/stories.json")
STORIES: dict[str, dict] = {s["id"]: s for s in DATA["stories"]}
MOVES: dict[str, dict] = {m["id"]: m for m in DATA["moves"]}
AXES = ("trust", "suspicion", "respect", "awe")


def running(state: State) -> list[dict]:
    """The stories this journey's level runs (its "stories": ids). A journey whose book was kept the older way (before
    D-70's quests) runs none: its stories stay as they were."""
    if (state.get("stories") or {}).get("version", BOOK_VERSION) != BOOK_VERSION:
        return []
    return [STORIES[story_id] for story_id in content.level(state).get("stories", []) if story_id in STORIES]


def _empty() -> dict:
    return {"version": BOOK_VERSION, "stages": {}, "outcomes": {}, "moves": [], "log": []}


def _record(state: State) -> dict:
    """The book as it stands, read-only (conditions read it on every check)."""
    return state.get("stories") or _empty()


def book(state: State) -> dict:
    """What has happened in the village's stories: steps reached, endings, moves made, who has been given what."""
    if not state.get("stories"):
        state["stories"] = _empty()
    return state["stories"]


# --- Secrets -------------------------------------------------------------------------------------------------


def _mind(npc: Npc) -> dict:
    """Someone's mind, read without writing: the clock checks stories every beat, after the beat is saved."""
    return npc.get("mind") or {}


def _seen_as(npc: Npc) -> dict:
    """How this person sees the stranger, read without writing (reputation.regard fills in its defaults)."""
    return reputation.regard({**npc, "mind": {"regard": dict(_mind(npc).get("regard") or {})}})


def all_secrets() -> dict[str, tuple[str, dict]]:
    """Every secret in the village: {secret_id: (whose, secret)}."""
    return {s["id"]: (npc_id, s) for npc_id, card in cast.CARDS.items() for s in card.get("secrets", []) if "id" in s}


def learned(state: State) -> set[str]:
    """What the stranger has been told: 'fact:<id>' and 'secret:<id>'."""
    keys = set()
    for entry in state.get("learned", []):
        if entry.get("fact"):
            keys.add(f"fact:{entry['fact']}")
        if entry.get("secret"):
            keys.add(f"secret:{entry['secret']}")
    return keys


def known_secrets(state: State) -> list[dict]:
    """The secrets the stranger knows (someone confided them): [{id, whose, text}]."""
    everything, keys = all_secrets(), learned(state)
    out = []
    for secret_id, (whose, secret) in everything.items():
        if f"secret:{secret_id}" in keys:
            owner = cast.find(state["npcs"], whose)
            out.append(
                {
                    "id": secret_id,
                    "whose": owner["name"] if owner else whose,
                    "owner_id": whose,
                    "text": secret["text"],
                    "known_by": [whose, *secret.get("known_by", [])],  # Whom it's no news to (D-63).
                }
            )
    return out


def helped(state: State, npc: Npc) -> bool:
    """The stranger has done this person (or their family) a real kindness: a gift, a wound treated, a deal kept."""
    family = {npc["id"], *cast.card(npc).get("family", [])}
    for memory in _mind(npc).get("memories", []):
        if memory["kind"] in ("help", "gift") and memory.get("victim") in family and memory.get("clarity") != "vague":
            return True
    return any(
        d.get("issuer") == npc["id"] and d.get("status") == "fulfilled"
        for d in (state.get("agreements") or {}).values()
    )


def confidable(state: State, npc: Npc) -> list[dict]:
    """Secrets this person could confide in the stranger now (code's side; the voice decides whether they do)."""
    if not npc.get("alive", True) or npc.get("down"):
        return []
    told = set(_mind(npc).get("confided", []))
    return [s for s in cast.card(npc).get("secrets", []) if "id" in s and s["id"] not in told and s.get("unlock")]


def heard(npc: Npc) -> list[str]:
    """Secrets about other people the stranger has told this person."""
    return [h["secret"] for h in _mind(npc).get("heard_secrets", [])]


def told_you(npc: Npc) -> list[str]:
    """What the stranger has told this person about others, for their own sheet: now theirs to know."""
    return [f"About {h['about']}: {h['text']}" for h in _mind(npc).get("heard_secrets", [])]


def tellable(state: State, listeners: list[Npc]) -> list[dict]:
    """What the stranger knows that they could pass on to these people now: secrets confided to them, each with
    whose it is. Only what at least one listener hasn't heard and doesn't own. [{id, about, what}]"""
    out = []
    for secret in known_secrets(state):
        if any(n["id"] not in secret["known_by"] and secret["id"] not in heard(n) for n in listeners):
            out.append({"id": secret["id"], "about": secret["whose"], "what": secret["text"]})
    return out


def tell(state: State, secret_ids: list[str], listeners: list[dict], event_id: int, now: int) -> list[dict]:
    """The stranger told these people these secrets (the scene's reading, checked here against what the stranger
    actually knows). The owner already knows their own. Returns [{secret, to}] for the journal."""
    known = {s["id"]: s for s in known_secrets(state)}
    told = []
    for secret_id in dict.fromkeys(secret_ids):
        if secret_id not in known:
            continue  # The stranger can only tell what they know.
        for npc in listeners:
            # Its owner, and whoever it's about (Darin's own rent), already know it: telling them passes nothing on.
            if npc["id"] in known[secret_id]["known_by"] or secret_id in heard(npc) or not npc.get("alive", True):
                continue
            cast.mind(npc).setdefault("heard_secrets", []).append(
                {
                    "secret": secret_id,
                    "from": "stranger",
                    "at": now,
                    "event": event_id,
                    "text": known[secret_id]["text"],
                    "about": known[secret_id]["whose"],
                }
            )
            told.append(
                {"secret": secret_id, "to": npc["id"], "to_name": npc["name"], "about": known[secret_id]["whose"]}
            )
    for delivery in told:
        receiver = cast.find(state["npcs"], delivery["to"])
        memory = {
            "kind": "disclosure",
            "event": event_id,
            "object_id": delivery["secret"],
            "victim": delivery["to"],
            "at": now,
            "severity": 1,
            "clarity": "clear",
            "source": "received",
            "summary": f"The stranger told {delivery['to_name']} a confidence about {delivery['about']}.",
            "short": "passed on a confidence",
        }
        reputation.remember(receiver, memory)
        cast.add_pending(state, receiver["id"], "decide", "heard a confidence")
        # Others may hear this disclosure only while present and within hearing range.
        for npc in state["npcs"]:
            if npc["id"] == receiver["id"] or not npc.get("alive", True) or npc.get("down"):
                continue
            if cast.distance(npc, state["player"]) <= tuning.HEAR_TALK_CELLS and paths.line_of_sight(
                state, cast.cell(npc), cast.player_cell(state)
            ):
                reputation.remember(npc, {**memory, "source": "overheard"})
                cast.add_pending(state, npc["id"], "decide", "overheard a confidence being disclosed")
    return told


# --- Conditions (the rule language: rules.py) --------------------------------------------------------------------


def _flags_match(obj: Thing, spec: dict) -> bool:
    """A thing answers a story's spec: any of its flags, as a registered flag or (D-62's extensible attributes) an
    attribute of that name not found false (D-63: a nail stroked on the lodestone is "magnetized" as an attribute)."""
    held = set(obj.get("flags", [])) | {
        a["name"] for a in obj.get("attributes", []) if a.get("name") and a.get("status") != "failed"
    }
    if spec.get("flags") and not set(spec["flags"]) & held:
        return False
    if spec.get("material") and spec["material"] not in obj.get("materials", []):
        return False
    return not (spec.get("name_has") and spec["name_has"] not in obj.get("name", "").lower())


def _whose(state: State, spec: dict, ctx: dict) -> Npc | None:
    return cast.find(state["npcs"], spec["npc"]) if spec.get("npc") else ctx.get("npc")


@rules.condition("learned", "any")
def _learned(state, spec, ctx):
    """The stranger has been told any of these (fact:id or secret:id)."""
    return bool(set(spec["any"]) & learned(state))


@rules.condition("move", "id")
def _moved(state, spec, ctx):
    return spec["id"] in _record(state)["moves"]


@rules.condition("told", "npc", "secrets")
def _told(state, spec, ctx):
    """The stranger told this person one of these secrets."""
    npc = _whose(state, spec, ctx)
    return bool(npc) and bool(set(spec["secrets"]) & set(heard(npc)))


@rules.condition("treated", "condition")
def _treated(state, spec, ctx):
    """This person's condition of this kind has been treated."""
    npc = _whose(state, spec, ctx)
    return bool(npc) and any(
        c["kind"] == spec["condition"] and c.get("treated", 0) > 0 for c in npc.get("conditions", [])
    )


@rules.condition("regard", "axis", "at_least")
def _regard(state, spec, ctx):
    npc = _whose(state, spec, ctx)
    return bool(npc) and _seen_as(npc).get(spec["axis"], 0.0) >= spec["at_least"]


@rules.condition("helped")
def _helped(state, spec, ctx):
    npc = _whose(state, spec, ctx)
    return bool(npc) and helped(state, npc)


def _shown(state: State, memory: dict, spec: dict) -> bool:
    """A memory of a working demonstration, seen clearly, that answers the spec (flags, wonder)."""
    if memory["kind"] != "demonstration" or not memory.get("works", True) or memory.get("clarity") != "clear":
        return False
    if spec.get("wonder") and memory.get("wonder") not in spec["wonder"]:
        return False
    if spec.get("flags"):
        shown = state["objects"].get(memory.get("object_id") or "")
        return bool(shown) and _flags_match(shown, {"flags": spec["flags"]})
    return True


@rules.condition("seen_demonstration", "npcs")
def _seen_demonstration(state, spec, ctx):
    """A working demonstration seen clearly by one of these people (of something with these flags, with this
    wonder, if asked)."""
    for npc_id in spec.get("npcs", []):
        npc = cast.find(state["npcs"], npc_id)
        if npc and any(_shown(state, m, spec) for m in _held(npc)):
            return True
    return False


def _gifts(state: State, spec: dict) -> set[str]:
    """The things the stranger gave one of these people that answer the spec (of this material, with these flags,
    by this name). Flags count only once the thing has been seen to work (D-62: an untested needle finds no north)."""
    people = set(spec.get("npc", []))
    return {
        o["id"]
        for o in state["objects"].values()
        if o.get("given_by") == "player"  # consequences.apply marks a gift (D-61).
        and (o.get("holder_id") in people or o.get("owner_id") in people)
        and _flags_match(o, spec)
        and (not spec.get("flags") or any(c.get("status") == "observed" for c in o.get("known_capabilities", [])))
        and (spec.get("water") != "clean" or _clean_water(o))  # Clean water, handed over (D-70).
    }


def _clean_water(obj: Thing) -> bool:
    return obj.get("water_l", 0) > 0 and not any(m["name"] == "fouled" for m in obj.get("mixture") or [])


@rules.condition("clean", "thing", "of")
def _clean(state, spec, ctx):
    """Nothing named so is fouling this thing or its water any more (D-70: the trough set right)."""
    obj = state["objects"].get(spec["thing"]) or {}
    there = [m["name"] for m in obj.get("mixture") or []] + [a["name"] for a in obj.get("attributes", [])]
    return bool(obj) and spec["of"] not in there


@rules.condition("mended", "thing")
def _mended(state, spec, ctx):
    """This thing is whole again: nothing lost to damage any more (D-70: Mara's tongs, repaired)."""
    obj = state["objects"].get(spec["thing"]) or {}
    return bool(obj) and not (obj.get("damage") or {}).get("lost_flags") and obj.get("condition") != "destroyed"


@rules.condition("given", "npc")
def _given(state, spec, ctx):
    """The stranger gave one of these people something (of this material, with these flags, by this name)."""
    return bool(_gifts(state, spec))


# --- Story moves (in conversation) ---------------------------------------------------------------------------


def moves_for(state: State, npc: Npc) -> list[dict]:
    """Story moves this person could make now: their own, for an open story, not yet made, possible by code."""
    record, here = _record(state), {s["id"] for s in running(state)}
    return [
        m
        for m in MOVES.values()
        if m["story"] in here
        and m["npc"] == npc["id"]
        and m["id"] not in record["moves"]
        and npc.get("alive", True)
        and _physical_conditions(state, m["when"])
    ]


def make_move(state: State, move_id: str, event_id: int) -> dict:
    record = book(state)
    record["moves"].append(move_id)
    record["log"].append(
        {"story": MOVES[move_id]["story"], "move": move_id, "at": state.get("sim_time_ms", 0), "event": event_id}
    )
    return MOVES[move_id]


# --- The stories moving on -------------------------------------------------------------------------------------
# A part of a story (a step or an ending) is reached when its condition holds, and reaches each person when they know
# it: their share of its effects applies once (how they see the stranger and others, what they now know and can tell,
# how they see the quest, what they'd ask of someone), and an ending's fact goes into their own context. Who knows is
# worked out from what each person holds (`knowers`), never guessed. One read-only check (`_due`) says what's due;
# `pending` asks it every beat, `tick` carries it out until nothing more is (D-70: a step in one quest can reach a step
# in another in the same beat, and someone who learns of it later still gets it, once).

BOOK_VERSION = 2
MAX_PASSES = 8


def _parts(story: dict):
    for stage in story.get("stages", []):
        yield "stage", stage
    for outcome in story.get("outcomes", []):
        yield "outcome", outcome


def part(story_id: str, kind: str, part_id: str) -> dict | None:
    """A story's step or ending by id."""
    story = STORIES.get(story_id) or {}
    return next((p for k, p in _parts(story) if k == kind and p["id"] == part_id), None)


def _is_reached(record: dict, story_id: str, kind: str, part_id: str) -> bool:
    if kind == "stage":
        return part_id in record["stages"].get(story_id, [])
    return part_id in record.get("milestones", {}).get(story_id, [])


def _due(state: State):
    """What tick would do now, touching nothing: ("reach", story, kind, part) for a part whose condition holds, and
    ("deliver", story, kind, part, npc_id) for a reached part someone now knows and hasn't yet been given."""
    record = _record(state)
    delivered = record.get("delivered", {})
    for story in running(state):
        for kind, each in _parts(story):
            if not _is_reached(record, story["id"], kind, each["id"]):
                if rules.holds(state, each["when"]):
                    yield ("reach", story, kind, each)
                continue
            if kind == "stage" and not each.get("effects"):
                continue
            given = set(delivered.get(f"{story['id']}/{each['id']}", []))
            for npc_id in sorted(known_by(state, each["when"]) - given):
                yield ("deliver", story, kind, each, npc_id)


def pending(state: State) -> bool:
    """Whether tick would change anything now (checked without touching the world: the clock asks every beat)."""
    return next(_due(state), None) is not None


def tick(state: State) -> bool:
    """Carry out everything due, pass after pass, until nothing more is."""
    record = book(state)
    now = state.get("sim_time_ms", 0)
    changed = False
    for _ in range(MAX_PASSES):
        due = list(_due(state))
        if not due:
            break
        changed = True
        for item in due:
            if item[0] == "reach":
                _reach(state, *item[1:], now)
            else:
                _deliver(state, *item[1:], now)
    for story_id in [k for k, v in record["stages"].items() if not v]:
        del record["stages"][story_id]  # Only stories the stranger has come into.
    return changed


def start(state: State) -> None:
    """A new journey: each quest's people start out with their side of it and what they'd ask of someone (D-70: they
    bring it up themselves when the stranger comes up to them)."""
    for story in running(state):
        _open(state, story)


def _open(state: State, story: dict) -> None:
    for npc_id, text in story.get("sides", {}).items():  # How each sees it at the start.
        _side(state, {"npc": npc_id, "text": text}, story)
    for npc_id, text in story.get("needs", {}).items():
        _need(state, {"npc": npc_id, "text": text}, story)


def _reach(state: State, story: dict, kind: str, each: dict, now: int) -> None:
    record = book(state)
    entry = {"story": story["id"], kind: each["id"], "at": now}
    if kind == "stage":
        record["stages"].setdefault(story["id"], []).append(each["id"])
    else:
        record.setdefault("milestones", {}).setdefault(story["id"], []).append(each["id"])
        record["outcomes"][story["id"]] = each["id"]
    record["log"].append(entry)
    _journal(state, story, kind, each["id"], each["summary"])


def _deliver(state: State, story: dict, kind: str, each: dict, npc_id: str, now: int) -> None:
    """A part reaches one person who now knows it: their share of its effects applies once, an ending's fact goes into
    their own context, and if it touched them they think again."""
    delivered = book(state).setdefault("delivered", {}).setdefault(f"{story['id']}/{each['id']}", [])
    delivered.append(npc_id)
    npc = cast.find(state["npcs"], npc_id)
    if npc is None or not npc.get("alive", True):
        return
    mine = [e for e in each.get("effects", []) if e.get("npc") == npc_id]
    for effect in mine:
        EFFECTS[effect["kind"]](state, effect, story)
    if kind == "outcome":
        summary = each["summary"].replace("You ", "The stranger ").replace(" you", " the stranger")
        cast.mind(npc).setdefault("story_facts", []).append(
            {"story": story["id"], "title": story["title"], "outcome": each["id"], "summary": summary, "at": now}
        )
    if mine:
        cast.add_pending(state, npc_id, "decide", "a turn in a story they're part of")


def _journal(state: State, story: dict, category: str, part_id: str, summary: str) -> None:
    state.setdefault("journal", []).append(
        {
            "kind": "story",
            "category": category,
            "story": story["id"],
            "title": story["title"],
            "part": part_id,
            "reason": summary,
        }
    )


# --- What a story's step or ending does, for each person it reaches ----------------------------------------------


def _shift_regard(state: State, spec: dict, story: dict | None = None) -> None:
    """How this person sees the stranger moves."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None or not npc.get("alive", True):
        return
    view = reputation.regard(npc)
    before = dict(view)
    for axis in AXES:
        if axis in spec:
            view[axis] = round(min(1.0, max(0.0, view.get(axis, 0.0) + spec[axis])), 3)
    reputation.regard_cue(npc, before, view)


def _shift_opinion(state: State, spec: dict, story: dict | None = None) -> None:
    """How this person feels about someone else moves."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None:
        return
    feeling = persona.opinions(npc).setdefault(spec["of"], {"warmth": 0.0, "text": ""})
    feeling["warmth"] = round(min(1.0, max(-1.0, feeling["warmth"] + spec["warmth"])), 2)


def _teach(state: State, spec: dict, story: dict | None = None) -> None:
    """This person now knows a fact or secret their card holds for later (D-70): theirs to tell, or keep."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None:
        return
    taught = cast.mind(npc).setdefault("taught", [])
    key = spec.get("fact") or spec.get("secret")
    if key and key not in taught:
        taught.append(key)


def _side(state: State, spec: dict, story: dict | None = None) -> None:
    """How this person now sees the quest (D-70): their side of it, in their own calls."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None or story is None:
        return
    cast.mind(npc).setdefault("sides", {})[story["id"]] = {
        "title": story["title"],
        "text": spec["text"][:240],
        "at": state.get("sim_time_ms", 0),
    }


def _reveal(state: State, spec: dict, story: dict | None = None) -> None:
    """A thing someone hid is out in the open now (D-70: Jory digs Mara's tongs out from under the scrap)."""
    obj = state["objects"].get(spec["thing"])
    if obj is not None and obj.get("hidden"):
        obj["hidden"] = None
        obj["revision"] = obj.get("revision", 0) + 1


def _need(state: State, spec: dict, story: dict | None = None) -> None:
    """What this person would ask of someone now, for this quest (D-70): they bring it up themselves. Empty: answered."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None or story is None:
        return
    needs = cast.mind(npc).setdefault("needs", {})
    if spec.get("text"):
        needs[story["id"]] = {"title": story["title"], "text": spec["text"][:160], "at": state.get("sim_time_ms", 0)}
    else:
        needs.pop(story["id"], None)


EFFECTS = {
    "shift_regard": _shift_regard,
    "shift_opinion": _shift_opinion,
    "teach": _teach,
    "side": _side,
    "need": _need,
    "reveal": _reveal,
}
NEEDS = {
    "shift_regard": ("npc",),
    "shift_opinion": ("npc", "of", "warmth"),
    "teach": ("npc",),
    "side": ("npc", "text"),
    "need": ("npc",),
    "reveal": ("npc", "thing"),
}


# --- Who knows that a condition came true (D-63, D-70) ------------------------------------------------------------


def _held(npc: Npc) -> list[dict]:
    """What this person holds as true: their evidence ledger (D-62), or their memories in an older journey."""
    return [m for m in (evidence.held(npc) or _mind(npc).get("memories", [])) if not m.get("doubted")]


def _holders(state: State, holds) -> set[str]:
    """Everyone alive who holds a memory that holds(memory)."""
    return {n["id"] for n in state["npcs"] if n.get("alive", True) and any(holds(m) for m in _held(n))}


KNOWERS: dict = {}


def knowing(kind: str):
    """Register who knows that a condition of this kind came true."""

    def register(fn):
        KNOWERS[kind] = fn
        return fn

    return register


def knowers(state: State, spec: dict) -> set[str] | None:
    """Who knows that this condition came true, from what each of them holds: never guessed from distance or from
    anything else they once saw. None for a kind nobody can be said to know (a regard, a "not"): inside an "all" it
    is a constraint, not knowledge, and is left out (D-70: kept_quiet never reached Tomas)."""
    fn = KNOWERS.get(spec["kind"])
    return fn(state, spec) if fn else None


def known_by(state: State, spec: dict) -> set[str]:
    return knowers(state, spec) or set()


@knowing("all")
def _knowers_all(state, spec):
    parts = [k for k in (knowers(state, p) for p in spec["of"]) if k is not None]
    return set.intersection(*parts) if parts else None


@knowing("any")
def _knowers_any(state, spec):
    parts = [k for p in spec["of"] if rules.holds(state, p) and (k := knowers(state, p)) is not None]
    return set().union(*parts) if parts else None


@knowing("learned")
def _knowers_learned(state, spec):  # Whoever told the stranger.
    return {
        entry["npc_id"]
        for entry in state.get("learned", [])
        if entry.get("npc_id") and ({f"fact:{entry.get('fact')}", f"secret:{entry.get('secret')}"} & set(spec["any"]))
    }


@knowing("told")
def _knowers_told(state, spec):  # Heard it passed on, overheard it, or were brought the news of it (the same event).
    told = _holders(state, lambda m: m["kind"] == "disclosure" and m.get("object_id") in spec["secrets"])
    events = {
        m["event"]
        for n in state["npcs"]
        for m in _held(n)
        if m["kind"] == "disclosure" and m.get("object_id") in spec["secrets"] and m.get("event") is not None
    }
    return told | _holders(state, lambda m: m.get("event") in events)


@knowing("given")
def _knowers_given(state, spec):
    gifts = _gifts(state, spec)
    return _holders(
        state, lambda m: m["kind"] == "gift" and bool(set(m.get("object_ids") or [m.get("object_id")]) & gifts)
    )


@knowing("installed")
def _knowers_installed(state, spec):  # Seen going up: an installation is shown, and anyone in sight sees it.
    return _holders(state, lambda m: m["kind"] == "demonstration" and m.get("object_id") == spec["thing"])


@knowing("treated")
def _knowers_treated(state, spec):
    patient = spec.get("npc")
    return ({patient} if patient else set()) | _holders(
        state, lambda m: m["kind"] == "help" and m.get("victim") == patient
    )


@knowing("seen_demonstration")
def _knowers_seen(state, spec):
    return _holders(state, lambda m: _shown(state, m, spec))


@knowing("move")
def _knowers_move(state, spec):  # The one who agreed, whoever overheard it, and whoever they told (the same event).
    made = [e["event"] for e in _record(state)["log"] if e.get("move") == spec["id"] and e.get("event")]
    mover = {MOVES[spec["id"]]["npc"]} if spec["id"] in MOVES and made else set()
    return mover | _holders(state, lambda m: m.get("event") in made)


@knowing("clean")
def _knowers_clean(state, spec):  # Its owner sees it set right.
    owner = cast.find(state["npcs"], (state["objects"].get(spec["thing"]) or {}).get("owner_id") or "")
    return {owner["id"]} if owner and owner.get("alive", True) else set()


@knowing("deal")
def _knowers_deal(state, spec):  # The one whose deal it is.
    return {spec["npc"]}


@knowing("reached")
def _knowers_reached(state, spec):  # Whoever knows the step or ending it names.
    named = part(spec["story"], "stage" if spec.get("stage") else "outcome", spec.get("stage") or spec.get("outcome"))
    return knowers(state, named["when"]) if named else None


@rules.condition("reached", "story")
def _reached(state, spec, ctx):
    """A step or ending of a story has been reached; with known, only if this rule's own person knows it (D-70)."""
    kind = "stage" if spec.get("stage") else "outcome"
    if not _is_reached(_record(state), spec["story"], kind, spec.get("stage") or spec.get("outcome")):
        return False
    if not spec.get("known"):
        return True
    npc = _whose(state, spec, ctx)
    return bool(npc) and npc["id"] in known_by(state, {"kind": "reached", **spec})


# --- For the people involved, and the journal ------------------------------------------------------------------


def _keys(spec) -> set[str]:
    """Every fact and secret a condition names ("fact:id", "secret:id"): what a lead must be to belong to a quest."""
    if isinstance(spec, list):
        return set().union(*(_keys(s) for s in spec)) if spec else set()
    if not isinstance(spec, dict):
        return set()
    found = set(spec.get("any", [])) if spec.get("kind") == "learned" else set()
    found |= {f"secret:{s}" for s in spec.get("secrets", [])} if spec.get("kind") == "told" else set()
    return found | _keys(spec.get("of", [])) | _keys(spec.get("when"))


def _quest_keys(story: dict) -> set[str]:
    parts = [p["when"] for _, p in _parts(story)] + [m["when"] for m in MOVES.values() if m["story"] == story["id"]]
    return _keys(parts)


def threads(state: State, story: dict) -> list[int]:
    """The stranger's own leads that belong to this quest (what someone told them), newest last: indices into their
    learned list, for the journal to show and pin. Only what they were told, never a step not yet reached."""
    keys = _quest_keys(story)
    found = [
        i
        for i, entry in enumerate(state.get("learned", []))
        if f"fact:{entry.get('fact')}" in keys or f"secret:{entry.get('secret')}" in keys
    ]
    return found[-3:]


def how_things_stand(state: State, npc: Npc) -> list[str]:
    """Endings of stories this person knows of, in plain words (for their own context)."""
    return [
        f"{f.get('title') or STORIES.get(f['story'], {}).get('title', f['story'])}: {f['summary']}"
        for f in _mind(npc).get("story_facts", [])
    ][-4:]


def page(state: State) -> list[dict] | None:
    """The journal's Stories page: the quests the stranger has come into, each with every step and ending they've
    reached, in the order it happened (whose side, if it came from someone). Never a step not yet reached. None in a
    level that runs none."""
    here = running(state)
    if not here:
        return None
    record, out = _record(state), []
    for story in here:
        steps = []
        for entry in record["log"]:
            if entry.get("story") != story["id"] or not (entry.get("stage") or entry.get("outcome")):
                continue
            kind = "stage" if entry.get("stage") else "outcome"
            each = part(story["id"], kind, entry.get(kind))
            if each is None:
                continue
            whose = cast.find(state["npcs"], each.get("from") or "")
            steps.append({"text": each["summary"], "kind": kind, "from": whose["name"] if whose else ""})
        if not steps:
            continue
        owner = cast.find(state["npcs"], story.get("people", {}).get("owner", ""))
        ended = [s["text"] for s in steps if s["kind"] == "outcome"]
        out.append(
            {
                "id": story["id"],
                "title": story["title"],
                "whose": owner["id"] if owner else "",
                "steps": steps,
                "threads": threads(state, story),
                "parts": [s["text"] for s in steps if s["kind"] == "stage"],
                "ended": ended[-1] if ended else None,
            }
        )
    return out


def _physical_conditions(state, spec):
    """Authored motives are suggestions; actual resources remain prerequisites."""
    if not spec:
        return True
    if spec.get("kind") in ("regard", "willing", "helped"):
        return True
    if spec.get("kind") == "all":
        return all(_physical_conditions(state, c) for c in spec["of"])
    if spec.get("kind") == "any":
        return any(_physical_conditions(state, c) for c in spec["of"])
    return rules.holds(state, spec)
