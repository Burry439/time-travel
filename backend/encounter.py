"""Encounters: face to face with the stranger, in rounds (D-28, D-48).

Anyone who comes up to address the stranger (a guard's halt, a confrontation, a threat, a demand
for payment) opens or joins an encounter; so does the stranger speaking or showing something to
someone. Time then moves in rounds instead of on the clock:

1. The stranger acts: say something, do something (a Try Something), wait, give up or walk away.
2. Code resolves that at once (a deed is judged like any other; people see it).
3. The scene answers (rounds.py, D-48): the person addressed, and anyone else in the conversation
   or close enough to join it, say what they would say and do, in one coherent turn. Nobody commits
   to anything before hearing the stranger, and nobody swings a weapon in a round: an attack starts a
   real-time fight (combat.py, D-41).
4. The world moves on by the round's length, so others can walk up and join.

Each participant has a purpose (why they are here). The encounter is hostile (the stranger can't just
wander off) while anyone is there about a crime or halting them at the gate; a guard who joins a
friendly conversation doesn't make it hostile. The whole round is one event. The encounter ends when
everyone in it has gone or died, the stranger walks away, the stranger dies, or they are let in.
"""
from __future__ import annotations

import copy
import math

import combat
import crafting
import minds
import talk

ROUND_MS = 5_000
FIGHT_WORDS_MS = 2_000  # Words shouted mid-fight take a moment, not a whole round (D-51).
BARRED_MS = 600_000  # How long the guards keep an arrested stranger away from the gate.
SOUTH_ROAD = (48, 66)  # Where the guards march an arrested stranger.
LEAVE_MS = 1_000  # Walking away takes a moment.
LOG_KEPT = 30
HOSTILE_PURPOSES = ("halt", "confront", "threaten", "demand_payment")
REASON_WORDS = {"halt": "a guard stopped the stranger at the gate", "confront": "they confronted the stranger",
                "threaten": "they came to threaten the stranger", "demand_payment": "they came to demand payment",
                "talk": "the stranger spoke to them", "joined": "they joined the conversation"}


# --- Opening, joining and ending ------------------------------------------------------------------

def active(state: dict) -> dict | None:
    return state.get("encounter") or None


def purpose(encounter: dict, npc_id: str) -> str:
    """Why this person is in the conversation (older saves: the encounter's one reason)."""
    return (encounter.get("purpose") or {}).get(npc_id) or encounter.get("reason", "talk")


def _reason(encounter: dict) -> str:
    """The encounter's overall character: the first hostile purpose among those present, else a talk."""
    return next((purpose(encounter, n) for n in encounter["participants"]
                 if purpose(encounter, n) in HOSTILE_PURPOSES), "talk")


def hostile(state: dict) -> bool:
    """An encounter the stranger can't simply walk off from: someone is here about a crime or a halt."""
    encounter = active(state)
    return bool(encounter) and _reason(encounter) != "talk"


def join(state: dict, npc: dict, reason: str, line: str | None, now: int) -> dict:
    """Open an encounter with this person, or bring them into the current one. An attack is a fight, not an
    encounter. While a fight is on the stranger can still speak to anyone (D-51), but nobody walks up to start a
    conversation of their own. A guard coming to halt a stranger who is already in a conversation joins it
    instead (D-48): the stranger is plainly being dealt with."""
    if reason == "attack":
        combat.start(state, [npc["id"]], now, "attack")
        return active(state)
    if combat.active(state) and reason not in ("talk", "joined"):
        minds._set_job(npc, {"kind": "watch", "until": now + 15_000}, now)
        return active(state)
    encounter = active(state)
    if encounter is None:
        encounter = state["encounter"] = {
            "id": f"enc_{state.get('event_seq', 0) + 1}_{npc['id'][4:]}", "participants": [], "purpose": {},
            "opened_by": npc["id"] if reason != "talk" else "player", "reason": reason, "round": 1, "log": [],
            "started_at": now}
    elif reason == "halt":
        reason, line = "joined", None  # Already in a conversation: they step over and listen, no "Halt!".
    if npc["id"] not in encounter["participants"]:
        encounter["participants"].append(npc["id"])
        encounter.setdefault("purpose", {})[npc["id"]] = reason
        words = (f"{npc['name']}: “{line}”" if line else f"{npc['name']} steps over." if reason == "joined"
                 else f"{npc['name']} faces you.")
        _log(encounter, npc["id"], "arrive", words)
    elif reason in HOSTILE_PURPOSES:
        encounter.setdefault("purpose", {})[npc["id"]] = reason  # Came back about something serious.
    encounter["reason"] = _reason(encounter)
    if reason != "talk" and not combat.fighting(state, npc):  # An attacker keeps attacking while they talk.
        minds._set_job(npc, {"kind": "encounter"}, now)
    # Face to face, people act in the scene: they don't also stop to think about what they saw.
    state["pending_minds"] = [p for p in state.get("pending_minds", [])
                              if not (p["npc_id"] == npc["id"] and p["kind"] == "decide")]
    return encounter


def _log(encounter: dict, who: str, kind: str, text: str, seen: str | None = None) -> dict:
    entry = {"round": encounter["round"], "who": who, "kind": kind, "text": text}
    if seen:
        entry["seen"] = seen
    encounter["log"].append(entry)
    del encounter["log"][:-LOG_KEPT]
    return entry


def prune(state: dict) -> None:
    """Drop people who are dead or have wandered off from a conversation; end it when nobody is left."""
    encounter = active(state)
    if encounter is None:
        return
    here = minds.player_cell(state)
    keep = []
    for npc_id in encounter["participants"]:
        npc = minds.find(state["npcs"], npc_id)
        if npc is None or not npc.get("alive", True):
            continue
        job = (npc.get("mind") or {}).get("job") or {}
        casual = purpose(encounter, npc_id) not in HOSTILE_PURPOSES
        away = math.dist(minds._cell(npc), here) > (6 if casual else 8)
        if job.get("kind") != "encounter" and (away or (casual and job.get("kind") not in (None, "watch"))):
            continue  # Went off to do something else, or the stranger walked away from them.
        keep.append(npc_id)
    encounter["participants"] = keep
    encounter["purpose"] = {k: v for k, v in (encounter.get("purpose") or {}).items() if k in keep}
    encounter["reason"] = _reason(encounter) if keep else encounter.get("reason", "talk")
    if not keep or not state["player"].get("alive", True) or state.get("inside_city"):
        end(state, state.get("sim_time_ms", 0))


def end(state: dict, now: int, walked_away: bool = False) -> None:
    """Everyone goes back to their day."""
    encounter = active(state)
    if encounter is None:
        return
    for npc_id in encounter["participants"]:
        npc = minds.find(state["npcs"], npc_id)
        if npc is None or not npc.get("alive", True):
            continue
        if ((npc.get("mind") or {}).get("job") or {}).get("kind") in (None, "encounter"):
            minds._set_job(npc, {"kind": "watch", "until": now + 15_000}, now)
    state["encounter"] = None


def open_for_talk(state: dict, npc: dict, now: int) -> dict:
    """The stranger speaks to (or shows something to) someone: a conversation, which is an encounter too."""
    return join(state, npc, "talk", None, now)


# --- Resolving the stranger's part of a round ------------------------------------------------------

def resolve(state: dict, run_id: str, action: dict, judged: dict | None, service_error: str | None,
            trace_id: str) -> tuple[dict, dict]:
    """The stranger's part of a round, on a copy of the world. Returns (draft world, round record: log entries,
    who was addressed, effort, what happened in words). The scene's replies and time passing come after."""
    draft = copy.deepcopy(state)
    now, journal = draft["sim_time_ms"], []
    if active(draft) is None:
        open_for_talk(draft, minds.find(draft["npcs"], action["target_id"]), now)
    encounter = draft["encounter"]
    kind, text = action["kind"], action.get("text", "")
    record = {"round": encounter["round"], "entries": [], "effort_seconds": 0, "entry": None, "replier": None,
              "fighting": bool(combat.active(draft)),
              "happened": [], "walked_away": False, "verdict": None, "seized_by": None,
              "cues_before": {n["id"]: ((n.get("mind") or {}).get("cue") or {}).get("key") for n in draft["npcs"]}}

    def note(who, entry_kind, words, seen=None):
        record["entries"].append(_log(encounter, who, entry_kind, words, seen))
        if seen:
            record["happened"].append(seen)

    if kind == "say":
        note("player", "say", f"You: “{talk.clean(text)}”")
    elif kind == "wait":
        note("player", "wait", "You wait and say nothing.", "The stranger waits and says nothing.")
    elif kind == "leave":
        record["walked_away"] = True
        note("player", "leave", "You turn and walk away.", "The stranger turns and walks away.")
    elif kind == "yield":
        note("player", "yield", "You raise your hands and give yourself up.", "The stranger surrenders.")
        guard = next((n for n in encounter["participants"] if minds.card(minds.find(draft["npcs"], n)).get("guard")),
                     None)
        if guard:  # A guard takes the surrender: an arrest.
            record["seized_by"] = guard
            note(guard, "seize", f"{minds.find(draft['npcs'], guard)['name']} takes you by the arm.",
                 "A guard took the stranger into custody.")
    elif kind == "do":
        payload, verdict, _ = crafting.resolve_attempt(draft, run_id, text, judged, service_error, trace_id, now)
        crafting.apply_payload(draft, payload)
        draft["sim_time_ms"] = now  # Time passes once, for the whole round.
        entry = payload["journal_entry"]
        record["entry"], record["effort_seconds"], record["verdict"] = entry, verdict["effort_seconds"], verdict
        perceptions = minds.perceive(draft, entry)
        minds.apply_perceptions(draft, perceptions)
        minds.after_deed(draft, entry)
        inside = set(encounter["participants"])
        draft["pending_minds"] = [p for p in draft.get("pending_minds", [])
                                  if not (p["npc_id"] in inside and p["kind"] == "decide")]
        seen = next((p["memory"]["summary"] for p in perceptions
                     if p["npc_id"] in inside and p["memory"].get("clarity") != "vague"), None)
        note("player", "do", entry["reason"], seen or f"The stranger tried to: “{talk.clean(text)}”")
    if record["walked_away"] and draft["player"].get("alive", True):
        _walked_off(draft, encounter, now, journal, note)
    draft["journal"].extend(journal)
    encounter["participants"] = [n for n in encounter["participants"]
                                 if (npc := minds.find(draft["npcs"], n)) and npc.get("alive", True)]
    # Who is addressed: the person named, else whoever opened the conversation, else the first there.
    target = action.get("target_id") if action.get("target_id") in encounter["participants"] else next(
        (n for n in [encounter["opened_by"]] + encounter["participants"] if n in encounter["participants"]), None)
    if target and draft["player"].get("alive", True) and not record["walked_away"] and not record["seized_by"]:
        record["replier"] = target
    return draft, record


def grievance(npc: dict) -> dict | None:
    """What the stranger did that this person holds against them (a crime they believe), if anything."""
    return minds.unresolved_crime(npc)


def _walked_off(draft: dict, encounter: dict, now: int, journal: list[dict], note) -> None:
    """Walking away is answered by why they came (D-44). A guard who came about a crime doesn't let the stranger
    stroll off: they give chase, to put them on the ground and arrest them (to kill only after real violence).
    Someone wronged shouts for the guards. A plain halt or a chat just ends."""
    fighting = set((combat.active(draft) or {}).get("attackers", []))
    for who in list(encounter["participants"]):
        npc = minds.find(draft["npcs"], who)
        wrong = grievance(npc) if npc else None
        if npc is None or who in fighting or wrong is None or not npc.get("alive", True) or npc.get("down"):
            continue
        if minds.card(npc).get("guard"):
            combat.start(draft, [who], now, "chase")
            note(who, "chase", f"{npc['name']}: “Stop right there!” {npc['name']} comes after you.",
                 f"The stranger walked off from {npc['name']}, who gave chase.")
        elif who not in (encounter.get("shouted") or []):
            encounter.setdefault("shouted", []).append(who)
            words = "Guards! Stop that one!"
            minds._say(npc, words, now, draft, journal)
            minds._raise_alarm(draft, npc, words, minds.HEAR_SHOUT_CELLS, now)
            note(who, "shout_for_help", f"{npc['name']}: “{words}”", f"{npc['name']} called for the guards.")


def finish(draft: dict, record: dict, now: int, reply: dict | list | None = None) -> None:
    """After the scene's lines (if any): keep or end the encounter."""
    encounter = active(draft)
    lines = [reply] if isinstance(reply, dict) else reply or []
    if encounter is None:  # e.g. someone attacked: words are over, and a fight is on.
        for said in lines:
            record["entries"].append({"round": record["round"], "who": said["npc_id"], "kind": said.get("kind", "reply"),
                                      "text": f"{said['name']}: “{said['line']}”"})
        record["ended"] = True
        return
    for said in lines:
        record["entries"].append(_log(encounter, said["npc_id"], said.get("kind", "reply"),
                                      f"{said['name']}: “{said['line']}”"))
    for npc_id in encounter["participants"]:  # How someone's view of the stranger shifted, as they'd show it.
        cue = (minds.mind(minds.find(draft["npcs"], npc_id)).get("cue") or {})
        if cue and cue.get("key") != record.get("cues_before", {}).get(npc_id):
            record["entries"].append(_log(encounter, npc_id, "cue", cue["text"]))
    if record.get("seized_by") and draft["player"].get("alive", True):
        arrest(draft, record, now)
        return
    over = (record["walked_away"] or not draft["player"].get("alive", True) or bool(draft.get("admitted"))
            or not encounter["participants"])
    if over:
        end(draft, now, walked_away=record["walked_away"])
        record["ended"] = True
        return
    record["ended"] = False
    encounter["round"] += 1
    encounter["reason"] = _reason(encounter)
    for npc_id in encounter["participants"]:
        npc = minds.find(draft["npcs"], npc_id)
        if purpose(encounter, npc_id) != "talk" and not combat.fighting(draft, npc):  # Stay face to face.
            minds._set_job(npc, {"kind": "encounter"}, now)


def arrest_player(state: dict, guard: dict, now: int) -> str:
    """Seized: other people's things go back to them, the stranger is marched down the south road and kept
    from the gate for a while, and the captain hears of it. Returns what happened, in words."""
    returned = []
    for obj in state["objects"].values():
        if obj["holder_id"] == "player" and obj["owner_id"] not in (None, "player") and obj.get("lent_to") != "player":
            obj["holder_id"] = obj["owner_id"]  # They take it back.
            returned.append(obj["name"])
    state["player"].update(x=SOUTH_ROAD[0], y=SOUTH_ROAD[1])
    state["barred_until"] = now + BARRED_MS
    words = (f"{guard['name']} and the guards march you back down the south road"
             + (f", and hand back the {', the '.join(returned)} to their owners" if returned else "")
             + ". You're not welcome at the gate for a while.")
    state["journal"].append({"kind": "arrest", "category": "arrested", "npc_id": guard["id"], "reason": words})
    minds.settle(state, "paid for with an arrest")  # The thefts are answered for (violence is not, D-46).
    captain = minds.find(state["npcs"], talk.CAPTAIN)
    if captain and captain.get("alive", True) and not captain.get("down"):
        minds.remember(captain, {"kind": "arrest", "severity": 1, "victim": None, "item": None,
                                 "event": state.get("event_seq", 0) + 1, "clarity": "told", "at": now,
                                 "source": f"told_by:{guard['id']}",
                                 "summary": f"{guard['name']} seized the stranger and marched them off down the south "
                                            f"road" + (f", taking back the {', the '.join(returned)}" if returned
                                                       else "") + ".",
                                 "short": "was arrested by the guards"})
    return words


def arrest(draft: dict, record: dict, now: int) -> None:
    """Seized in a round: the arrest, logged in the encounter, and play goes on."""
    words = arrest_player(draft, minds.find(draft["npcs"], record["seized_by"]), now)
    record["entries"].append(_log(active(draft), "player", "arrested", words))
    record["arrested"] = True
    end(draft, now)
    record["ended"] = True


def round_ms(record: dict) -> int:
    if record.get("arrested"):
        return LEAVE_MS
    if record["walked_away"]:
        return LEAVE_MS
    if record.get("fighting"):
        return max(FIGHT_WORDS_MS, record["effort_seconds"] * 1000)
    return max(ROUND_MS, record["effort_seconds"] * 1000)
