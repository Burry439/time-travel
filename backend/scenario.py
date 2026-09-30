"""A scenario: a fixed story on the map told in steps, all of it content (data/content/tutorial.json: the first
morning, GDD D-50, D-52, D-57). Each step's cards are read first (the client says so: `read`), and only then does
its check count, one step at a time. Checks and triggers are conditions in the rule language (rules.py), decided
by code, so any way the player finds counts; what the story does (someone speaks, walks over, lends something,
a bout begins) are effects, registered here. The parts it gives people for a while (Kade the teacher) are roles,
read by the core rules through rules.role. Progress happens only through `tick`, `read` and `ui`, saved as
`tutorial` events (routes_tutorial), so replay is exact.
"""

from __future__ import annotations

from collections.abc import Callable

import cast
import combat
import content
import device
import gatekeeping
import gear
import m2
import reputation
import rules
import speech
from shapes import State

STORY = content.TUTORIAL
STEPS: list[dict] = STORY["steps"]


def active(state: State) -> bool:
    """The story is on, and from this version of it (an older journey's steps no longer line up)."""
    return rules.scene_step(state) is not None


def step(state: State) -> dict | None:
    return rules.scene_step(state)


def setup(state: State) -> None:
    """A scenario journey: its own things in the world (lent gear on the people who lend it), and the story at its
    first step."""
    for spec in STORY.get("things", []):
        holder = cast.find(state["npcs"], spec.get("carried_by") or "")
        at = {"x": holder["x"], "y": holder["y"]} if holder else {}
        state["objects"][spec["id"]] = m2.authored({**spec, **at})
    state["tutorial"] = {
        "step": 0,
        "started_at": 0,
        "fired": [],
        "done": False,
        "reacted": [],
        "read": -1,
        "ui_done": [],
        "flags": {},
        "version": STORY["version"],
    }
    state["device_log"] = []
    state["journal"] = state.get("journal") or []
    _start_step(state, 0)


def _ctx(state: State, now: int) -> dict:
    return {"now": now, "progress": state.get("tutorial") or {}}


# --- The story moving on -------------------------------------------------------------------------------------


def read_cards(state: State) -> bool:
    """The step's cards have been read (the client's Next): from now its check counts."""
    if not active(state) or state["tutorial"].get("read", -1) >= state["tutorial"]["step"]:
        return False
    state["tutorial"]["read"] = state["tutorial"]["step"]
    return True


def ui_done(state: State, key: str) -> bool:
    """A ui action the story teaches happened (the pack opened, a closer look, the book read)."""
    if not active(state) or key in state["tutorial"].setdefault("ui_done", []):
        return False
    state["tutorial"]["ui_done"].append(key)
    return True


def tick(state: State) -> bool:
    """React to anything drastic and keep people to their roles; then, once the current step's cards are read,
    fire its triggers and complete it if its outcome has happened. One step at a time (D-52): the next step waits
    for its own cards."""
    if not active(state):
        return False
    tutorial = state["tutorial"]
    now = state.get("sim_time_ms", 0)
    changed = _react(state, now)
    changed = _stay(state, now) or changed
    current = STEPS[tutorial["step"]]
    if tutorial.get("read", tutorial["step"]) < tutorial["step"]:
        return changed  # Still reading its cards.
    ctx = _ctx(state, now)
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and rules.holds(state, trigger["when"], ctx):
            tutorial["fired"].append(key)
            run(state, trigger["do"], now)
            changed = True
    if not rules.holds(state, current["check"], ctx):
        return changed
    _complete(state, current, now)
    return True


def _complete(state: State, current: dict, now: int) -> None:
    tutorial = state["tutorial"]
    if current.get("done"):
        device.says(state, current["done"], "story")
    run(state, current.get("on_done", []), now)
    if tutorial["step"] + 1 >= len(STEPS):
        tutorial["done"] = True
        state["objective"] = "Get inside the city"
        return
    tutorial["step"] += 1
    _start_step(state, now)


def skip(state: State) -> None:
    """Developer: complete the current step as if its outcome had happened (its triggers too, except any marked
    not to be skipped, like a bout)."""
    if not active(state):
        return
    tutorial = state["tutorial"]
    current = STEPS[tutorial["step"]]
    now = state.get("sim_time_ms", 0)
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and trigger.get("skippable", True):
            tutorial["fired"].append(key)
            run(state, trigger["do"], now)
    tutorial["read"] = tutorial["step"]
    _complete(state, current, now)


def _start_step(state: State, now: int) -> None:
    current = STEPS[state["tutorial"]["step"]]
    state["tutorial"]["started_at"] = now
    state["tutorial"]["started_seq"] = state.get("event_seq", 0)  # Anything made after this is this step's.
    state["objective"] = current.get("task") or current["title"]
    for line in current.get("cards", []):
        device.says(state, line, "story")
    run(state, current.get("on_start", []), now)


def _react(state: State, now: int) -> bool:
    """The device notices anything drastic, once each: a death, an arrest, the stranger dying."""
    tutorial = state["tutorial"]
    changed = False
    seen = {
        "dead": not state["player"].get("alive", True),
        "arrested": int(state.get("barred_until") or 0) > now,
        "killed": any(not n.get("alive", True) for n in state["npcs"]),
    }
    for kind, happened in seen.items():
        if happened and kind not in tutorial["reacted"]:
            tutorial["reacted"].append(kind)
            device.says(state, STORY["reactions"][kind], "reaction")
            changed = True
    return changed


def _stay(state: State, now: int) -> bool:
    """Someone whose role is to stay with the stranger (Kade, once he has come over, until he goes to the captain)
    has their stay renewed whenever they're only standing or watching. Anything else they're doing is left alone."""
    changed = False
    for part in STORY.get("roles", []):
        npc = cast.find(state["npcs"], part["npc"])
        if npc is None or not part.get("stays") or rules.role(state, npc) is not part:
            continue
        if not rules.holds(state, part["stays"], _ctx(state, now)):
            continue
        job = (npc.get("mind") or {}).get("job") or {}
        if job.get("kind") not in (None, "watch") or job.get("until", 0) >= now + 60_000:
            continue
        cast.watch(npc, now, part["stay_s"] * 1000)
        changed = True
    return changed


# --- What the story does -----------------------------------------------------------------------------------------

Effect = Callable[[State, dict, dict], None]
EFFECTS: dict[str, Effect] = {}
NEEDS: dict[str, tuple[str, ...]] = {}  # The fields each kind must have (the content check reads these).


def effect(kind: str, *needs: str) -> Callable[[Effect], Effect]:
    """Register an effect kind, fn(state, spec, ctx), and the fields its spec must have."""

    def register(fn: Effect) -> Effect:
        EFFECTS[kind] = fn
        NEEDS[kind] = needs
        return fn

    return register


def run(state: State, effects: list[dict], now: int) -> None:
    """Carry out effects in order; one with a `when` only if it holds."""
    ctx = _ctx(state, now)
    for spec in effects:
        if spec.get("when") and not rules.holds(state, spec["when"], ctx):
            continue
        EFFECTS[spec["kind"]](state, spec, ctx)


def _person(state: State, spec: dict) -> dict | None:
    return cast.find(state["npcs"], spec.get("npc", ""))


def _text(state: State, parts, ctx: dict) -> str:
    """Words written in content: a string, or parts, each said only if its `when` holds."""
    if isinstance(parts, str):
        return parts
    return "".join(
        p if isinstance(p, str) else p["text"]
        for p in parts
        if isinstance(p, str) or rules.holds(state, p.get("when"), ctx)
    )


@effect("npc_says", "npc", "text")
def _says(state, spec, ctx):
    npc = _person(state, spec)
    if npc and npc.get("alive", True):
        speech.say(npc, spec["text"], ctx["now"], state, state["journal"])
        cast.mind(npc).setdefault("talk", []).append({"who": "them", "text": spec["text"], "at": ctx["now"]})


@effect("approach", "npc")
def _approach(state, spec, ctx):
    npc = _person(state, spec)
    if npc and npc.get("alive", True) and not npc.get("down"):
        job = {
            "kind": "approach",
            "target": "player",
            "stop": spec.get("stop", 1.5),
            "speed": "walk",
            "then": "tutorial",
        }
        cast.set_job(npc, job, ctx["now"])


@effect("hold", "npc", "seconds")
def _hold(state, spec, ctx):
    """Stand and talk a moment: nobody walks off mid-word."""
    npc, now = _person(state, spec), ctx["now"]
    if npc and npc.get("alive", True):
        for person in [npc] + [cast.find(state["npcs"], other) for other in spec.get("with", [])]:
            if person:
                controller = person.get("controller") or {}
                controller["next_at_ms"] = max(controller.get("next_at_ms", 0), now + spec["seconds"] * 1000)
                cast.watch(person, now, spec["seconds"] * 1000)


@effect("keep", "npc", "seconds")
def _keep(state, spec, ctx):
    """Stay with the stranger a while (Kade for his lessons)."""
    npc = _person(state, spec)
    if npc and npc.get("alive", True):
        cast.watch(npc, ctx["now"], spec["seconds"] * 1000)


@effect("vouch", "npc")
def _vouch(state, spec, ctx):
    """Off to the captain to speak for the stranger (D-57). What they say may depend on what they know: a speech's
    notes are what the story remembers they knew when they went."""
    npc = _person(state, spec)
    if not (npc and npc.get("alive", True) and not npc.get("down")):
        return
    words = {**STORY.get("speeches", {}).get(spec.get("speech"), {}), **spec}
    for key, known in words.get("notes", {}).items():
        state["tutorial"].setdefault("flags", {})[key] = rules.holds(state, known, ctx)
    why, summary = _text(state, words["why"], ctx), _text(state, words["summary"], ctx)
    gatekeeping.speak_for(state, npc, why, summary, None, ctx["now"])


@effect("admit", "npc")
def _admit(state, spec, ctx):
    """The captain lets them in on a word he holds."""
    npc = _person(state, spec)
    if npc and npc.get("alive", True) and not state.get("admitted"):
        because = [m["summary"] for m in cast.mind(npc)["memories"] if reputation.is_evidence(m)][-4:]
        state.update(admitted={"by": npc["id"], "event_id": None, "because": because}, gate_open=True)


@effect("lend", "npc", "objects")
def _lend(state, spec, ctx):
    npc = _person(state, spec)
    if npc:
        for oid in spec["objects"]:
            obj = state["objects"].get(oid)
            if obj and obj.get("holder_id") == npc["id"]:
                obj.update(holder_id="player", lent_to="player")


@effect("hurt", "npc", "condition")
def _hurt(state, spec, ctx):
    """The story's own problem: Jory's burn."""
    npc = _person(state, spec)
    if npc and npc.get("alive", True):
        wound = spec["condition"]
        if not any(c["kind"] == wound["kind"] for c in npc.get("conditions", [])):
            gear.add_condition(npc, wound, ctx["now"])
            npc["health"] = max(1, npc.get("health", 100) - wound.get("severity", 10))


@effect("spar", "npc")
def _spar(state, spec, ctx):
    npc = _person(state, spec)
    if npc:
        combat.start_spar(state, npc, ctx["now"], spec.get("with"))


@effect("errand", "npc", "to", "message")
def _errand(state, spec, ctx):
    """Someone goes and tells someone (D-51): one written line, and only the story moves on."""
    npc = _person(state, spec)
    if npc and npc.get("alive", True):
        job = {"kind": "tell", "target": spec["to"], "speed": "walk", "message": spec["message"], "event": None}
        cast.set_job(npc, {**job, "quiet": True}, ctx["now"])
