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
    """The stories this journey's level runs (its "stories": ids)."""
    return [STORIES[story_id] for story_id in content.level(state).get("stories", [])]


def _record(state: State) -> dict:
    """The book as it stands, read-only (conditions read it on every check)."""
    return state.get("stories") or {"stages": {}, "outcomes": {}, "moves": [], "log": []}


def book(state: State) -> dict:
    """What has happened in the village's stories: stages reached, outcomes, moves made."""
    if not state.get("stories"):
        state["stories"] = {"stages": {}, "outcomes": {}, "moves": [], "log": []}
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
                {"id": secret_id, "whose": owner["name"] if owner else whose, "owner_id": whose, "text": secret["text"]}
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
        if any(n["id"] != secret["owner_id"] and secret["id"] not in heard(n) for n in listeners):
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
            if npc["id"] == known[secret_id]["owner_id"] or secret_id in heard(npc) or not npc.get("alive", True):
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
    if spec.get("flags") and not set(spec["flags"]) & set(obj.get("flags", [])):
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


@rules.condition("knows_story", "story", "stage")
def _knows_story(state, spec, ctx):
    return spec["stage"] in _record(state)["stages"].get(spec["story"], [])


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
    }


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


def pending(state: State) -> bool:
    """Whether tick would change anything now (checked without touching the world: the clock asks every beat)."""
    record = _record(state)
    if any(_arrived(state, waiting) for waiting in record.get("waiting", [])):
        return True
    for story in running(state):
        reached = record["stages"].get(story["id"], [])
        if any(s["id"] not in reached and rules.holds(state, s["when"]) for s in story.get("stages", [])):
            return True
        if any(
            o["id"] not in record.get("milestones", {}).get(story["id"], []) and rules.holds(state, o["when"])
            for o in story["outcomes"]
        ):
            return True
    return False


def tick(state: State) -> bool:
    """Record newly reached stages and outcomes while leaving later consequences observable."""
    record = book(state)
    now = state.get("sim_time_ms", 0)
    changed = False
    for story in running(state):
        reached = record["stages"].setdefault(story["id"], [])
        for stage in story.get("stages", []):
            if stage["id"] not in reached and rules.holds(state, stage["when"]):
                reached.append(stage["id"])
                record["log"].append({"story": story["id"], "stage": stage["id"], "at": now})
                _journal(state, story, "stage", stage["id"], stage["summary"])
                changed = True
        completed = record.setdefault("milestones", {}).setdefault(story["id"], [])
        for outcome in story.get("outcomes", []):
            if outcome["id"] not in completed and rules.holds(state, outcome["when"]):
                record["outcomes"][story["id"]] = outcome["id"]
                record["log"].append({"story": story["id"], "outcome": outcome["id"], "at": now})
                completed.append(outcome["id"])
                # It reaches each person concerned (and anyone who already knows) when they know it (D-63).
                concerned = _concerned(story, outcome) | knowers(state, outcome["when"])
                record.setdefault("waiting", []).extend(
                    {"story": story["id"], "outcome": outcome["id"], "npc": npc_id} for npc_id in sorted(concerned)
                )
                _journal(state, story, "outcome", outcome["id"], outcome["summary"])
                changed = True
    changed = _deliver(state, now) or changed
    for story_id in [k for k, v in record["stages"].items() if not v]:
        del record["stages"][story_id]  # Only stories the stranger has come into.
    return changed


def _journal(state: State, story: dict, category: str, part: str, summary: str) -> None:
    state.setdefault("journal", []).append(
        {
            "kind": "story",
            "category": category,
            "story": story["id"],
            "title": story["title"],
            "part": part,
            "reason": summary,
        }
    )


def _shift_regard(state: State, spec: dict) -> None:
    """How this person sees the stranger moves (a story's outcome)."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None or not npc.get("alive", True):
        return
    view = reputation.regard(npc)
    before = dict(view)
    for axis in AXES:
        if axis in spec:
            view[axis] = round(min(1.0, max(0.0, view.get(axis, 0.0) + spec[axis])), 3)
    reputation.regard_cue(npc, before, view)


def _shift_opinion(state: State, spec: dict) -> None:
    """How this person feels about someone else moves."""
    npc = cast.find(state["npcs"], spec["npc"])
    if npc is None:
        return
    feeling = persona.opinions(npc).setdefault(spec["of"], {"warmth": 0.0, "text": ""})
    feeling["warmth"] = round(min(1.0, max(-1.0, feeling["warmth"] + spec["warmth"])), 2)


# What a story's outcome does (its own two kinds: a story ends with how people see the stranger and each other).
EFFECTS = {"shift_regard": _shift_regard, "shift_opinion": _shift_opinion}
NEEDS = {"shift_regard": ("npc",), "shift_opinion": ("npc", "of", "warmth")}


# --- Who knows an outcome, and its reaching them (D-63) ------------------------------------------------------


def _held(npc: Npc) -> list[dict]:
    """What this person holds as true: their evidence ledger (D-62), or their memories in an older journey."""
    return [m for m in (evidence.held(npc) or _mind(npc).get("memories", [])) if not m.get("doubted")]


def _holders(state: State, holds) -> set[str]:
    """Everyone alive who holds a memory that holds(memory)."""
    return {n["id"] for n in state["npcs"] if n.get("alive", True) and any(holds(m) for m in _held(n))}


def knowers(state: State, spec: dict) -> set[str]:
    """Who knows that this condition came true, from what each of them holds: never guessed from distance or from
    anything else they once saw. An "all" is known to those who know every part; an "any" to those who know a part
    that holds. What the stranger learned is known to whoever told them."""
    kind = spec["kind"]
    if kind == "all":
        parts = [knowers(state, part) for part in spec["of"]]
        return set.intersection(*parts) if parts else set()
    if kind == "any":
        return set().union(*(knowers(state, part) for part in spec["of"] if rules.holds(state, part)))
    if kind == "learned":
        return {
            entry["npc_id"]
            for entry in state.get("learned", [])
            if entry.get("npc_id")
            and ({f"fact:{entry.get('fact')}", f"secret:{entry.get('secret')}"} & set(spec["any"]))
        }
    if kind == "told":  # Heard it passed on, overheard it, or were brought the news of it (the same event).
        told = _holders(state, lambda m: m["kind"] == "disclosure" and m.get("object_id") in spec["secrets"])
        events = {
            m["event"]
            for n in state["npcs"]
            for m in _held(n)
            if m["kind"] == "disclosure" and m.get("object_id") in spec["secrets"] and m.get("event") is not None
        }
        return told | _holders(state, lambda m: m.get("event") in events)
    if kind == "given":
        gifts = _gifts(state, spec)
        return _holders(
            state, lambda m: m["kind"] == "gift" and bool(set(m.get("object_ids") or [m.get("object_id")]) & gifts)
        )
    if kind == "installed":  # Seen going up (perception: an installation is shown, and anyone in sight sees it).
        return _holders(state, lambda m: m["kind"] == "demonstration" and m.get("object_id") == spec["thing"])
    if kind == "treated":
        patient = spec.get("npc")
        return ({patient} if patient else set()) | _holders(
            state, lambda m: m["kind"] == "help" and m.get("victim") == patient
        )
    if kind == "seen_demonstration":
        return _holders(state, lambda m: _shown(state, m, spec))
    if kind == "move":  # The one who agreed, whoever overheard it, and whoever they told (the same event).
        made = [e["event"] for e in _record(state)["log"] if e.get("move") == spec["id"] and e.get("event")]
        mover = {MOVES[spec["id"]]["npc"]} if spec["id"] in MOVES and made else set()
        return mover | _holders(state, lambda m: m.get("event") in made)
    return set()


def _concerned(story: dict, outcome: dict) -> set[str]:
    """Whom an outcome concerns: the story's people and everyone its effects are about."""
    people = story.get("people", {})
    return (
        {people.get("owner")}
        | set(people.get("helps", []))
        | set(people.get("opposes", []))
        | {e["npc"] for e in outcome.get("effects", [])}
    ) - {None}


def _arrived(state: State, waiting: dict) -> bool:
    outcome = next(o for o in STORIES[waiting["story"]]["outcomes"] if o["id"] == waiting["outcome"])
    return waiting["npc"] in knowers(state, outcome["when"])


def _deliver(state: State, now: int) -> bool:
    """Outcomes reach the people who now know them: the fact goes into their own context, their authored reaction
    (the outcome's effects for them) applies once, and they think again. The rest keep waiting."""
    record = book(state)
    arrived = [w for w in record.get("waiting", []) if _arrived(state, w)]
    for waiting in arrived:
        record["waiting"].remove(waiting)
        npc = cast.find(state["npcs"], waiting["npc"])
        if npc is None or not npc.get("alive", True):
            continue
        story = STORIES[waiting["story"]]
        outcome = next(o for o in story["outcomes"] if o["id"] == waiting["outcome"])
        for effect in outcome.get("effects", []):
            if effect["npc"] == npc["id"]:
                EFFECTS[effect["kind"]](state, effect)
        summary = outcome["summary"].replace("You ", "The stranger ").replace(" you", " the stranger")
        cast.mind(npc).setdefault("story_facts", []).append(
            {"story": story["id"], "outcome": outcome["id"], "summary": summary, "at": now}
        )
        cast.add_pending(state, npc["id"], "decide", "a story outcome they learned")
    return bool(arrived)


# --- For the people involved, and the journal ------------------------------------------------------------------


def how_things_stand(state: State, npc: Npc) -> list[str]:
    """Stories this person is part of that have been settled, in plain words (for their character sheet)."""
    return [
        f"{STORIES[f['story']]['title']}: {f['summary']}"
        for f in _mind(npc).get("story_facts", [])
        if f["story"] in STORIES
    ]


def page(state: State) -> list[dict] | None:
    """The journal's Stories page: the storylines the stranger has come into, each with what they've come to know or
    seen happen (in the order it happened) and how it ended, if it has. None in a level that runs none."""
    here = running(state)
    if not here:
        return None
    record, out = _record(state), []
    for story in here:
        reached = record["stages"].get(story["id"], [])
        ended = record["outcomes"].get(story["id"])
        if not reached and not ended:
            continue
        stages = {s["id"]: s["summary"] for s in story.get("stages", [])}
        outcome = next((o["summary"] for o in story["outcomes"] if o["id"] == ended), None)
        owner = cast.find(state["npcs"], story.get("people", {}).get("owner", ""))
        out.append(
            {
                "id": story["id"],
                "title": story["title"],
                "whose": owner["id"] if owner else "",
                "parts": [stages[s] for s in reached if s in stages],
                "ended": outcome,
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
