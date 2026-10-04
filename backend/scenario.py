"""A scenario: a guided story on a level's map told in steps, all of it content (data/content/levels: the training
levels, GDD D-50, D-52, D-59). Each step's cards are read first (the client says so: `read`), and only then does
its check count, one step at a time. Checks and triggers are conditions in the rule language (rules.py), decided
by code, so any way the player finds counts; what the story does (someone speaks, lends something, a bout begins)
are effects, registered here. The parts it gives people for a while (Hal the teacher) are roles,
read by the core rules through rules.role. Progress happens only through `tick`, `read` and `ui`, saved as
`tutorial` events (routes_tutorial), so replay is exact. What a moment has people say is a story beat (beats.py):
said in their own words in the reply that brought it about, if they did, and as written if not.
"""

from __future__ import annotations

from collections.abc import Callable

import beats
import cast
import combat
import content
import device
import encounter
import gear
import reputation
import rules
import speech
import talk
from shapes import State


def story(state: State) -> dict:
    """The journey's level: its steps, roles and the device's reactions."""
    return content.level(state)


def steps(state: State) -> list[dict]:
    return story(state).get("steps") or []


def active(state: State) -> bool:
    """The story is on, and from this version of it (an older journey's steps no longer line up)."""
    return rules.scene_step(state) is not None


def step(state: State) -> dict | None:
    return rules.scene_step(state)


def setup(state: State) -> None:
    """A guided journey: the story at its first step (its things are already in the world, m2.seed_objects)."""
    state["tutorial"] = {
        "step": 0,
        "started_at": 0,
        "fired": [],
        "done": False,
        "reacted": [],
        "read": -1,
        "ui_done": [],
        "version": story(state)["version"],
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
    current = steps(state)[tutorial["step"]]
    if tutorial.get("read", tutorial["step"]) < tutorial["step"]:
        return changed  # Still reading its cards.
    ctx = _ctx(state, now)
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and rules.holds(state, trigger["when"], ctx):
            tutorial["fired"].append(key)
            run(state, trigger["do"], now, key)
            changed = True
    if not rules.holds(state, current["check"], ctx):
        return changed
    waiting = beats.waiting_on(state, current)  # Someone's telling: it comes when they tell it (D-59).
    if waiting is not None:
        return _estranged(state, current, waiting) or changed
    _complete(state, current, now)
    return True


def _estranged(state: State, current: dict, npc: dict) -> bool:
    """The device says, once, when a step waits on someone who won't do anything for the stranger now."""
    key = f"estranged:{current['id']}:{npc['id']}"
    if not npc.get("alive", True) or reputation.willing(state, npc) or key in state["tutorial"]["reacted"]:
        return False
    state["tutorial"]["reacted"].append(key)
    words = story(state).get("reactions", {}).get("estranged") or ESTRANGED
    device.says(state, words.format(name=npc["name"], Esc="{Esc}"), "reaction")
    return True


def _complete(state: State, current: dict, now: int) -> None:
    tutorial = state["tutorial"]
    if current.get("done"):
        device.says(state, current["done"], "story")
    run(state, current.get("on_done", []), now, current["id"])
    if tutorial["step"] + 1 >= len(steps(state)):
        tutorial["done"] = True
        state["objective"] = story(state)["objective"]
        return
    tutorial["step"] += 1
    _start_step(state, now)


def skip(state: State) -> None:
    """Developer: complete the current step as if its outcome had happened (its triggers too, except any marked
    not to be skipped, like a bout)."""
    if not active(state):
        return
    tutorial = state["tutorial"]
    current = steps(state)[tutorial["step"]]
    now = state.get("sim_time_ms", 0)
    for trigger in current.get("triggers", []):
        key = f"{current['id']}:{trigger['id']}"
        if key not in tutorial["fired"] and trigger.get("skippable", True):
            tutorial["fired"].append(key)
            run(state, trigger["do"], now, key)
    tutorial["read"] = tutorial["step"]
    _complete(state, current, now)


def _start_step(state: State, now: int) -> None:
    current = steps(state)[state["tutorial"]["step"]]
    state["tutorial"]["started_at"] = now
    state["tutorial"]["started_seq"] = state.get("event_seq", 0)  # Anything made after this is this step's.
    state["objective"] = current.get("task") or current["title"]
    for line in current.get("cards", []):
        device.says(state, line, "story")
    run(state, current.get("on_start", []), now, f"{current['id']}:start")


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
            device.says(state, story(state)["reactions"][kind], "reaction")
            changed = True
    return changed


def _stay(state: State, now: int) -> bool:
    """Someone whose role is to stay with the stranger (Hal, through his lessons) has their stay renewed whenever
    they're only standing or watching. Anything else they're doing is left alone."""
    changed = False
    for part in story(state).get("roles", []):
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


# What a story asks of a person toward the stranger: theirs to do, only if they're willing (D-59). The rest (a burn,
# robbers stepping out, standing a moment) is the world going on.
FAVOURS = ("npc_says", "lend", "spar", "errand", "lead", "offer")
WORDS = ("npc_says", "lead", "offer")  # What they'd tell the stranger: not if they kept it to themselves.
ESTRANGED = (
    "{name} won't do anything for you now, not after what happened. What you do here is real: put it right if you "
    "can, or Rewind to before it ({Esc}, then Rewind)."
)


def run(state: State, effects: list[dict], now: int, moment: str | None = None) -> None:
    """Carry out effects in order; one with a `when` only if it holds, one a person does for the stranger only if they
    will. moment is the story moment they belong to (a step's id, step:trigger or step:start), whose beats people
    may already have told in their own words."""
    ctx = _ctx(state, now) | {"moment": moment}
    for spec in effects:
        if spec.get("when") and not rules.holds(state, spec["when"], ctx):
            continue
        if _goes_ahead(state, spec, ctx):
            EFFECTS[spec["kind"]](state, spec, ctx)


def _goes_ahead(state: State, spec: dict, ctx: dict) -> bool:
    """Whether the person an effect asks something of does it: the story proposes, people decide (D-59). Scalded,
    robbed or afraid, Ulf neither asks for his tea nor lends his pot; someone who kept their piece back in their
    reply isn't spoken over. A step's opening lines are the world going on (Tam burns his hand), only theirs to say
    while they can."""
    npc = _person(state, spec)
    if spec["kind"] not in FAVOURS or npc is None or npc is state["player"]:
        return True
    moment = ctx.get("moment") or ""
    if spec["kind"] == "npc_says" and moment.endswith(":start"):
        return npc.get("alive", True) and not npc.get("down")
    if spec["kind"] in WORDS and beats.held(npc, moment):
        return False
    return reputation.willing(state, npc)


def _person(state: State, spec: dict) -> dict | None:
    """Who an effect is about: someone in the level, or the stranger ("player")."""
    if spec.get("npc") == "player":
        return state["player"]
    return cast.find(state["npcs"], spec.get("npc", ""))


@effect("npc_says", "npc", "text")
def _says(state, spec, ctx):
    """Someone says an authored line: only what they haven't just said in their own words (a story beat)."""
    npc = _person(state, spec)
    if npc is None or not npc.get("alive", True):
        return
    answer = None if npc is state["player"] else beats.answered(npc, ctx.get("moment"))
    text = beats.left_to_say(spec["text"], answer)
    if text:
        speech.say(npc, text, ctx["now"], state, state["journal"])
        cast.mind(npc).setdefault("talk", []).append({"who": "them", "text": text, "at": ctx["now"]})
        encounter.said_aside(state, npc, text)  # Face to face, the conversation shows it too.
        if answer:  # Their bubble shows it as one thing said: their own words, then the rest.
            cast.mind(npc)["said"]["text"] = f"{answer} {text}"


@effect("hold_up", "npcs")
def _hold_up(state, spec, ctx):
    """Robbers step out (D-59): each walks up to the stranger and threatens them, with their own line (says)."""
    for npc_id in spec["npcs"]:
        npc = cast.find(state["npcs"], npc_id)
        if npc and npc.get("alive", True) and not npc.get("down") and cast.robbing(npc):
            job = {
                "kind": "approach",
                "target": "player",
                "stop": 2.5,
                "speed": "walk",
                "then": "threaten",
                "line": (spec.get("says") or {}).get(npc_id),
                "line_id": None,
            }
            cast.set_job(npc, job, ctx["now"])


@effect("lend", "npc", "objects")
def _lend(state, spec, ctx):
    """Their own things, the stranger's to use (D-55: using them isn't theft): handed over if they hold them, or
    where they lie (the materials on a workbench, D-59)."""
    npc = _person(state, spec)
    if npc:
        for oid in spec["objects"]:
            obj = state["objects"].get(oid)
            if obj and obj.get("holder_id") == npc["id"]:
                obj.update(holder_id="player", lent_to="player")
            elif obj and obj.get("owner_id") == npc["id"] and obj.get("holder_id") is None:
                obj["lent_to"] = "player"


@effect("hurt", "npc", "condition")
def _hurt(state, spec, ctx):
    """The story's own problem: Jory's burn, or the stranger's own cut (D-59)."""
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
    """Someone goes and tells someone (D-51): one written line, and only the story moves on; or, voiced, a real
    errand: they tell it in their own words, and the listener answers and decides what to do (Pip tells Ada what the
    stranger did for his gran, D-59)."""
    npc = _person(state, spec)
    if npc and npc.get("alive", True):
        job = {"kind": "tell", "target": spec["to"], "speed": "walk", "message": spec["message"], "event": None}
        cast.set_job(npc, {**job, "quiet": not spec.get("voiced")}, ctx["now"])


@effect("lead", "npc", "lead")
def _lead(state, spec, ctx):
    """Someone tells the stranger something worth keeping: a lead in the journal. One the story asks of the stranger
    carries done_when, a condition, and counts as done when it holds (views.lead_done)."""
    npc = _person(state, spec)
    learned = state.setdefault("learned", [])
    known = next((e for e in learned if npc and e.get("npc_id") == npc["id"] and e.get("lead") == spec["lead"]), None)
    if known:  # Already in the journal, as their reply shared it: kept once, in their words.
        if spec.get("done_when"):
            known.update(asks=True, done_when=spec["done_when"])
        return
    if npc:
        said = spec.get("said", spec["lead"])
        answer = beats.answered(npc, ctx.get("moment"))
        said = answer if beats.says_all(answer, said) else said  # Their own words, when those carried it.
        entry = {"npc_id": npc["id"], "name": npc["name"], "said": said, "event_id": None}
        entry["lead"] = spec["lead"]
        if spec.get("done_when"):
            entry.update(asks=True, done_when=spec["done_when"])
        learned.append(entry)


@effect("offer", "npc", "offer")
def _offer(state, spec, ctx):
    """Someone offers the stranger one of their deals (their card's offers): a lead, and what the job needs lent.
    Agreeing to it and doing it are the stranger's, as any deal (D-55)."""
    npc = _person(state, spec)
    if npc and not any(d.get("template") == spec["offer"] for d in (state.get("agreements") or {}).values()):
        says, answer = spec.get("says", ""), beats.answered(npc, ctx.get("moment"))
        says = answer if says and beats.says_all(answer, says) else says
        talk.propose(state, npc, spec["offer"], None, says, state.setdefault("learned", []), [])
