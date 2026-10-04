"""Time passing for people: routines and the jobs they chose move them along, errands are delivered, guards
watch the gate, bodies bleed and mend, and the village's own life is scheduled. Every clock beat, every
round and every deed that takes time runs through advance_people (GDD 4.5)."""

from __future__ import annotations

import copy

import cast
import combat
import encounter
import gear
import heat
import minds
import npc_sim
import paths
import persona
import reputation
import speech
import tuning
import village
from shapes import Job, Npc, State


def _target_cell(state: State, npcs: list[Npc], job: Job) -> tuple[int, int] | None:
    if "goal" in job:
        return tuple(job["goal"])
    if job.get("target") == "player":
        return cast.player_cell(state) if state["player"].get("alive", True) else None
    target = cast.find(npcs, job.get("target") or "")
    return cast.cell(target) if target and target.get("alive", True) else None


def _deliver_report(state: State, npc: Npc, target: dict, now: int, journal: list[dict], job: Job) -> None:
    worst = reputation.worst_memory(npc)
    if worst is None:
        return
    speech.say(
        npc,
        job.get("line") or f"{target['name']}! The stranger {worst['short']}!",
        now,
        state,
        journal,
        job.get("line_id"),
    )
    for known in cast.mind(npc)["memories"]:
        known["reported"] = True  # The teller has done their part.
    if reputation.knows(target, worst):
        return
    memory = {
        **{
            k: worst.get(k)
            for k in (
                "kind",
                "severity",
                "short",
                "victim",
                "item",
                "object_id",
                "evidence_id",
                "actor_id",
                "works",
                "revision",
                "application",
            )
        },
        "event": worst.get("event"),
        "clarity": "told",
        "summary": f"{npc['name']} told them: {worst['summary']}",
        "at": now,
        "source": f"told_by:{npc['id']}",
    }
    reputation.remember(target, memory)
    cast.mind(target)["rethinks"] = 0
    cast.add_pending(state, target["id"], "decide", f"told by {npc['name']}")


def _deliver_vouch(state: State, npc: Npc, captain: Npc, now: int, journal: list[dict], job: Job) -> None:
    """Someone speaks for the stranger to the captain: evidence he weighs when the stranger asks to enter."""
    # Whoever decides here, by title or name: the city's captain, or a ferryman (D-59: Ilse called Gorm "Captain").
    to = "Captain" if "captain" in cast.card(captain)["role"].lower() else captain["name"]
    choices = speech.choose_lines(state, npc, "vouch", {"why": job["why"], "to": to, "name": captain["name"]})
    line_id, text = choices[0] if choices else (None, f"{to}, I'll speak for the stranger: {job['why']}")
    speech.say(npc, text, now, state, journal, line_id)
    reputation.remember(
        captain,
        {
            "kind": "vouch",
            "severity": 1,
            "by": npc["id"],
            "victim": None,
            "item": None,
            "event": job.get("event"),
            "clarity": "told",
            "source": f"told_by:{npc['id']}",
            "at": now,
            "summary": job["summary"],
            "short": f"has {npc['name']}'s word",
        },
    )


def _deliver_message(state: State, npc: Npc, target: dict, now: int, journal: list[dict], job: Job) -> None:
    """An errand promised in conversation (D-51): they found the person and told them. The listener remembers it,
    and may do something about it."""
    message = job["message"]
    if job.get("quiet"):  # The tutorial's errands: a written line, and only its story moves on.
        speech.say(npc, f"{target['name']}, a word. {message}", now, state, journal)
    reputation.remember(
        target,
        {
            "kind": "told",
            "severity": 0,
            "by": npc["id"],
            "victim": None,
            "item": None,
            "event": job.get("event"),
            "clarity": "told",
            "source": f"told_by:{npc['id']}",
            "at": now,
            "summary": f"{npc['name']} came and told them: {message}",
            "short": f"heard about from {npc['name']}",
        },
    )
    heard = persona.knows(target).setdefault("heard", [])
    heard.append({"from": npc["id"], "from_name": npc["name"], "text": message, "at": now})
    del heard[:-8]
    if not job.get("quiet"):  # They stop and talk; what's said, and what the listener does, is the voice's (D-54).
        for person, other in ((npc, target), (target, npc)):
            controller = person.get("controller") or {}
            controller["next_at_ms"] = max(controller.get("next_at_ms", 0), now + 12_000)
            cast.mind(person)["chatting_with"] = {"id": other["id"], "until": now + 12_000}
        pending = state.setdefault("pending_minds", [])
        pending[:] = [p for p in pending if not (p["npc_id"] == target["id"] and p["kind"] == "told")]
        pending.append({"npc_id": target["id"], "kind": "told", "why": npc["id"], "message": message, "at": now})


# What someone on an errand does when they reach the person it was for.
DELIVERIES = {"report": _deliver_report, "vouch": _deliver_vouch, "tell": _deliver_message}


def dealt_with_recently(npcs: list[Npc], now: int) -> bool:
    """A guard has just been speaking with the stranger or been shown something by them (D-48)."""
    for guard in npcs:
        if not cast.card(guard).get("guard") or not guard.get("mind"):
            continue
        last_talk = max((t.get("at", -(10**9)) for t in guard["mind"].get("talk", [])), default=-(10**9))
        last_seen = max(
            (
                m.get("at", -(10**9))
                for m in guard["mind"].get("memories", [])
                if m["kind"] in reputation.EVIDENCE_KINDS + ("talk",) and not reputation.hearsay(m)
            ),
            default=-(10**9),
        )
        if max(last_talk, last_seen) >= now - tuning.DEALT_WITH_MS:
            return True
    return False


def _gate_watch(state: State, npcs: list[Npc], now: int) -> None:
    """No model involved: the nearest free guard walks up to a stranger at the gate who hasn't been admitted,
    unless the stranger is already being dealt with (a conversation, or a guard they've just talked to)."""
    if (gate := paths.gate(state)) is None:
        return
    x, y = cast.player_cell(state)
    guards = [g for g in npcs if g.get("alive", True) and cast.card(g).get("guard")]
    at_gate = paths.in_zone((x, y), gate["approach"])
    dealt_with = bool(state.get("encounter")) or dealt_with_recently(npcs, now)
    if (
        state.get("admitted")
        or state.get("inside_city")
        or not state["player"].get("alive", True)
        or not at_gate
        or dealt_with
    ):
        for guard in guards:  # The stranger left, may pass, or is being dealt with: nobody needs stopping.
            if ((guard.get("mind") or {}).get("job") or {}).get("then") == "halt":
                cast.set_job(guard, None, now)
        return
    if any(
        (g.get("mind") or {}).get("halted_at", -(10**9)) > now - tuning.HALT_EVERY_MS
        or ((g.get("mind") or {}).get("job") or {}).get("then") == "halt"
        for g in guards
    ):
        return
    free = [
        g
        for g in guards
        if not (g.get("mind") or {}).get("job") and cast.distance(g, (x, y)) <= tuning.HALT_REACH_CELLS
    ]
    if free:
        guard = min(free, key=lambda g: cast.distance(g, (x, y)))
        cast.set_job(guard, {"kind": "approach", "target": "player", "stop": 2.0, "speed": "walk", "then": "halt"}, now)


def _maybe_reconsider(state: State, npc: Npc, why: str) -> None:
    """Someone shaken by a serious event nobody official has heard about thinks again (a few times at most)."""
    my_mind = cast.mind(npc)
    worst = reputation.worst_memory(npc)
    if worst is None or worst["severity"] < 2 or worst.get("reported") or cast.card(npc).get("guard"):
        return
    if my_mind.get("rethinks", 0) >= tuning.MAX_RETHINKS or not state["player"].get("alive", True):
        return
    my_mind["rethinks"] = my_mind.get("rethinks", 0) + 1
    cast.add_pending(state, npc["id"], "decide", why)


def _ambient(state: State, npc: Npc, now: int, blocked: paths.Grid) -> None:
    """No model involved: wary people face the stranger; frightened people keep their distance."""
    my_mind = npc.get("mind")
    if not my_mind or my_mind.get("job") or not state["player"].get("alive", True):
        if my_mind is not None:
            my_mind["facing_player"] = bool(my_mind.get("job")) and my_mind["job"]["kind"] in (
                "watch",
                "approach",
                "attack",
                "fight",
            )
        return
    feelings = my_mind.get("feelings", {})
    distance = cast.distance(npc, state["player"])
    wary = feelings.get("fear", 0) > 0.3 or feelings.get("anger", 0) > 0.3
    my_mind["facing_player"] = wary and distance <= tuning.AMBIENT_CELLS
    if feelings.get("fear", 0) > 0.6 and distance < 5:
        cast.set_job(
            npc,
            {"kind": "flee", "goal": minds.away_goal(state, npc, blocked), "speed": "walk", "until": now + 10_000},
            now,
        )


def advance_world(state: State, elapsed_ms: int, now: int) -> tuple[list[dict], list[dict], dict]:
    """People follow routines or their current job for elapsed_ms; blows are rolled; ambient rules apply.

    Returns (npcs, journal lines, player). May queue thinking in state["pending_minds"].
    """
    npcs = npc_sim.advance_npcs(state, state["npcs"], elapsed_ms, now)
    working = copy.copy(state)
    working["npcs"] = npcs
    working["player"] = copy.deepcopy(state["player"])
    working["encounter"] = copy.deepcopy(state.get("encounter"))
    working["fight"] = copy.deepcopy(state.get("fight"))
    working["objects"] = dict(state.get("objects") or {})  # Copy-on-write: combat.change_object replaces entries.
    working["projectiles"] = copy.deepcopy(state.get("projectiles") or [])
    working.pop("objects_changed", None)
    working.pop("objects_added", None)
    journal: list[dict] = []
    blocked = paths.grid(state)
    end = now + elapsed_ms
    talking = set((working.get("encounter") or {}).get("participants", []))
    for npc in npcs:
        if not npc.get("alive", True) or npc.get("down"):
            continue
        if ((npc.get("mind") or {}).get("knows") or {}).get("notes") and npc["id"] not in talking:
            cast.add_pending(working, npc["id"], "recollect", "the conversation ended")  # Remember it (D-36).
        _on_the_job(working, npcs, npc, elapsed_ms, end, blocked, journal)
    combat_running = combat.busy(working)
    combat.tick(working, npcs, elapsed_ms, now, blocked, journal)  # Chronological impacts and body time.
    if not combat_running:
        _bodies(working, npcs, elapsed_ms, now, journal)  # Bleeding, festering, waking, mending (D-49).
    if not working.get("encounter") and not working.get("fight"):
        _gate_watch(working, npcs, end)  # Nobody needs halting while the stranger is already face to face with someone.
    encounter.prune(working)
    village.schedule(working, npcs, end)
    state["pending_minds"] = working.get("pending_minds", state.get("pending_minds", []))
    state["encounter"] = working.get("encounter")
    state["fight"] = working.get("fight")
    if working.get("subdued_by"):
        state["subdued_by"] = working["subdued_by"]
    state["projectiles"] = working.get("projectiles") or []
    for field in ("facts", "incidents"):
        if field in working:
            state[field] = working[field]
    state["people_objects_changed"] = working.get("objects_changed") or {}
    state["people_objects_added"] = working.get("objects_added") or []
    for npc in npcs:  # How each stands toward the stranger (D-55), kept current for the journal and toasts.
        if npc.get("mind"):
            reputation.update_standing(npc)
    return npcs, journal, working["player"]


def _on_the_job(
    state: State, npcs: list[Npc], npc: Npc, elapsed_ms: int, end: int, blocked: paths.Grid, journal: list[dict]
) -> None:
    """One person's job for this stretch of time: keep watching, give up, or walk on toward where it takes them
    and do it when they get there. Without a job, the calm rules apply."""
    job = (npc.get("mind") or {}).get("job")
    if not job:
        _ambient(state, npc, end, blocked)
        return
    if job["kind"] in ("encounter", "fight"):
        return  # Face to face in rounds, or fighting (combat.tick moves them): not on the clock here.
    if job.get("wait_until", 0) > end:
        return  # e.g. an attacker the stranger just walked away from, a moment before they give chase.
    if job["kind"] == "watch":
        if end >= job["until"]:
            cast.set_job(npc, None, end)
            _maybe_reconsider(state, npc, "still shaken")
        return
    goal = _target_cell(state, npcs, job)
    if goal is None or (job["kind"] == "attack" and cast.distance(npc, goal) > tuning.GIVE_UP_CELLS):
        cast.set_job(npc, None, end)
        return
    stop = {"flee": 0.0, "report": 1.5, "attack": 1.5, "vouch": 1.5}.get(job["kind"], job.get("stop", 1.5))
    if _walk(npc, goal, stop, elapsed_ms, job, blocked):
        _arrived(state, npcs, npc, job, end, journal)


def _walk(npc: Npc, goal: tuple[int, int], stop: float, elapsed_ms: int, job: Job, blocked: paths.Grid) -> bool:
    """Step toward the goal at their pace (running or walking) for this long; whether they're there now."""
    controller = npc.get("controller") or {}
    carry = controller.get("step_carry_ms", 0) + elapsed_ms
    step_ms = tuning.RUN_STEP_MS if job.get("speed") == "run" else tuning.WALK_STEP_MS
    while carry >= step_ms and cast.distance(npc, goal) > stop:
        carry -= step_ms
        step = paths.next_step(cast.cell(npc), goal, stop, blocked)
        if step is None:
            break
        npc["x"], npc["y"] = step
    controller["step_carry_ms"] = carry if cast.distance(npc, goal) > stop else 0
    return cast.distance(npc, goal) <= stop


def _arrived(state: State, npcs: list[Npc], npc: Npc, job: Job, end: int, journal: list[dict]) -> None:
    """They got where their job took them: safe (and watching), the person they had word for, or the stranger."""
    kind, then = job["kind"], job.get("then")
    if kind == "flee":
        cast.watch(npc, end, tuning.WATCH_MS)
    elif kind in DELIVERIES:
        target = cast.find(npcs, job["target"])
        if target and (kind != "tell" or target.get("alive", True)):
            DELIVERIES[kind](state, npc, target, end, journal, job)
        cast.watch(npc, end, tuning.WATCH_SHORT_MS)
    elif kind == "approach" and then == "halt":
        _halt(state, npcs, npc, end, journal)
    elif kind == "approach" and then in ("confront", "threaten", "demand_payment"):
        text = job.get("line") or "What do you think you're doing?!"
        speech.say(npc, text, end, state, journal, job.get("line_id"), category="address")
        cast.mind(npc).setdefault("talk", []).append({"who": "them", "text": text, "at": end})
        encounter.join(state, npc, then, text, end)
    elif kind == "approach":
        if job.get("line"):
            speech.say(npc, job["line"], end, state, journal, job.get("line_id"))
        cast.watch(npc, end, tuning.WATCH_MS)
        (npc.get("controller") or {})["activity"] = "work"
        if then == "help":
            _tend(state, npc, cast.find(npcs, job.get("target") or ""), end, journal)
        _maybe_reconsider(state, npc, "tending the hurt person")
    elif kind == "attack":
        encounter.join(state, npc, "attack", None, end)  # An older chase arriving: it's a fight now.


def _halt(state: State, npcs: list[Npc], npc: Npc, end: int, journal: list[dict]) -> None:
    """A guard who came to stop the stranger at the gate: joins a conversation that's already on, stands by if a
    guard has just dealt with them, or halts them."""
    if state.get("encounter"):
        encounter.join(state, npc, "halt", None, end)
    elif dealt_with_recently(npcs, end):
        cast.watch(npc, end, tuning.WATCH_MS)
    else:
        choices = speech.choose_lines(state, npc, "halt", {})
        line_id, text = choices[0] if choices else (None, "Halt! State your business.")
        speech.say(npc, text, end, state, journal, line_id, category="halt")
        cast.mind(npc)["halted_at"] = end
        cast.mind(npc).setdefault("talk", []).append({"who": "them", "text": text, "at": end})
        encounter.join(state, npc, "halt", text, end)


def _tend(state: State, helper: Npc, patient: Npc | None, now: int, journal: list[dict]) -> None:
    """Someone who came to help binds what they can (D-49): with a remedy they carry, or a strip torn from their
    own clothes (which slows heavy bleeding but won't close it)."""
    if patient is None or not patient.get("alive", True):
        return
    carried = [o for o in state["objects"].values() if o.get("holder_id") == helper["id"] and gear.remedy_for(o)]
    strip = {
        "id": None,
        "name": "strip of cloth",
        "materials": ["linen"],
        "mass_kg": 0.05,
        "flags": ["flexible"],
        "gear": {"kind": "remedy", "class": "bandage", "covers": [], "quality": "crude"},
    }
    tended = []
    for index, condition in enumerate(gear.conditions(patient)):
        if condition not in gear.untreated(patient):
            continue
        remedy = next((o for o in carried if condition["kind"] in gear.remedy_for(o)["treats"]), None)
        use = remedy or (strip if condition["kind"] == "bleeding" else None)
        if use is None or not gear.treat(patient, index, use, now)["ok"]:
            continue
        tended.append(gear.describe(condition).removeprefix("the "))
        if remedy is not None and gear.remedy_for(remedy).get("consumed"):
            # Copy-on-write, so the tick's changes reach the event.

            combat.change_object(state, remedy["id"], holder_id="used", condition="used up")
            carried.remove(remedy)
    if tended and cast.distance(patient, state["player"]) <= tuning.SIGHT_CELLS:
        journal.append(
            {
                "kind": "people",
                "category": "tend",
                "npc_id": helper["id"],
                "reason": f"{helper['name']} binds {patient['name']}'s {tended[0]}.",
            }
        )


def _bodies(state: State, npcs: list[Npc], elapsed_ms: int, now: int, journal: list[dict]) -> None:
    """Bodies on the clock (gear.advance): wounds bleed and fester, the knocked-out wake, the unhurt mend."""
    end = now + elapsed_ms
    player = state["player"]
    was_alive = player.get("alive", True)
    gear.advance(player, elapsed_ms, now)
    if was_alive and not player.get("alive", True):
        journal.append(
            {
                "kind": "fight",
                "category": "killed",
                "npc_id": "player",
                "reason": "You've lost too much blood. Everything goes dark.",
            }
        )
    for npc in npcs:
        if not npc.get("alive", True) or not npc.get("conditions"):
            continue
        was_down = bool(npc.get("down"))
        gear.advance(npc, elapsed_ms, now)
        controller = npc.get("controller") or {}
        if not npc.get("alive", True):
            controller.update(activity="dead", path=[], source="dead")
            if npc.get("mind"):
                npc["mind"]["job"] = None
            if cast.distance(npc, state["player"]) <= tuning.SIGHT_CELLS:
                journal.append(
                    {
                        "kind": "fight",
                        "category": "killed",
                        "npc_id": npc["id"],
                        "reason": f"{npc['name']} bleeds out and lies still.",
                    }
                )
        elif was_down and not npc.get("down"):  # Came round after being knocked senseless.
            controller.update(activity="look", source="routine", path=[])
            cast.watch(npc, end, tuning.WATCH_MS)
            cast.mind(npc)["fresh"] = "came round after being knocked senseless"


def advance_people(state: State, elapsed_ms: int) -> dict:
    """Payload fields for time passing: routines, the jobs people chose, encounters starting."""
    probe = dict(state)
    probe["pending_minds"] = list(state.get("pending_minds", []))
    npcs, heard, player = advance_world(probe, elapsed_ms, state["sim_time_ms"])

    changed = heat.age_objects(state, elapsed_ms, state["sim_time_ms"])
    for object_id, fields in (probe.get("people_objects_changed") or {}).items():  # Arrows landing, shields worn.
        changed.setdefault(object_id, {}).update(fields)
    payload = {
        "npcs": npcs,
        "player": player,
        "pending_minds": probe["pending_minds"],
        "people_journal": heard,
        "encounter": probe.get("encounter"),
        "fight": probe.get("fight"),
        "objects_changed": changed,
        **{k: probe[k] for k in ("facts", "incidents") if k in probe},
        "projectiles": probe.get("projectiles") or [],
    }
    if probe.get("people_objects_added"):
        payload["objects_added"] = probe["people_objects_added"]
    if probe.get("subdued_by"):  # Beaten down by someone who meant only to subdue (D-44).
        _subdued(state, payload, probe["subdued_by"], state["sim_time_ms"] + elapsed_ms)
    return payload


def _robbed(state: State, payload: dict, robber: Npc, now: int) -> None:
    """Beaten down by robbers (D-59): they take what they came for and let the stranger go, in the payload."""
    draft = {
        "objects": copy.deepcopy(state["objects"]),
        "player": payload["player"],
        "npcs": payload["npcs"],
        "journal": [],
        "encounter": payload.get("encounter"),
        "fight": payload.get("fight"),
        "sim_time_ms": now,
        "event_seq": state["event_seq"],
    }
    words = encounter.rob(draft, robber, now)
    for object_id, obj in draft["objects"].items():
        before = state["objects"][object_id]
        for field in ("holder_id", "owner_id"):
            if obj[field] != before[field]:
                payload["objects_changed"].setdefault(object_id, {})[field] = obj[field]
    payload.update(encounter=draft.get("encounter"), fight=draft.get("fight"))
    entry = {"kind": "fight", "category": "robbed", "text": words, "sim_time_ms": now}
    payload["people_journal"] = payload["people_journal"] + draft["journal"] + [entry]


def _subdued(state: State, payload: dict, by: str, now: int) -> None:
    """A guard arrests the stranger they put on the ground (stolen things go back, marched off, barred for a while);
    anyone else just stops. Everything lands in the payload, so replay needs no rules."""
    subduer = cast.find(payload["npcs"], by)
    guard = (
        subduer
        if cast.card(subduer).get("guard")
        else next(
            (
                n
                for n in payload["npcs"]
                if cast.card(n).get("guard")
                and not n.get("down")
                and n.get("alive", True)
                and n["id"] in (state.get("fight") or {}).get("attackers", [])
            ),
            None,
        )
    )
    if guard is None:
        if cast.robbing(subduer):
            _robbed(state, payload, subduer, now)
        return
    draft = {
        "objects": copy.deepcopy(state["objects"]),
        "player": payload["player"],
        "npcs": payload["npcs"],
        "journal": [],
        "sim_time_ms": now,
        "event_seq": state["event_seq"],
    }
    encounter.arrest_player(draft, guard, now)
    for object_id, obj in draft["objects"].items():
        if obj["holder_id"] != state["objects"][object_id]["holder_id"]:
            payload["objects_changed"].setdefault(object_id, {})["holder_id"] = obj["holder_id"]
    payload["barred_until"] = draft["barred_until"]
    payload["people_journal"] = payload["people_journal"] + draft["journal"]
