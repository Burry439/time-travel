"""Real-time fights (GDD D-41): no rounds, no dice.

A fight starts with the stranger's judged first strike (or someone deciding to attack them). From then
on it runs on the clock: each attacker closes in and winds up a swing with their weapon; when the
swing lands, it hits if the stranger is still within reach and misses if they have stepped away. The
stranger fights back with their fists (Space), which land if the target is within reach. Damage is
fixed by weapon against armour: a sword wounds the unarmoured stranger badly and a second blow kills;
fists do nothing against mail. Nobody rolls anything: what happens is what would happen.

It ends when every attacker is dead, down or gone, when the stranger gets away, dies, or gives up
(guards then arrest them). Everything is recorded in the clock and strike events, so replay is exact.
"""
from __future__ import annotations

import math

import minds

WEAPONS: dict[str, dict] = minds._CARD_FILE["weapons"]  # Fixed damage vs the unarmoured stranger, wind-up, reach.
RECOVER_MS = 1_300  # Between one swing landing and the next wind-up.
PUNCH = {"none": 15, "padded": 5, "mail": 0}  # The stranger's fist against each armour.
ARM_REACH = WEAPONS["fists"]["reach"]
PUNCH_RECOVER_MS = 700
DOWN_AT = 25  # At or below this health someone is down: alive, out of the fight.
GIVE_UP_CELLS = minds.GIVE_UP_CELLS
LOG_KEPT = 12


def active(state: dict) -> dict | None:
    return state.get("fight") or None


def armor(npc: dict) -> str:
    return minds.card(npc).get("armor", "none")


def weapon(npc: dict) -> str:
    return minds.card(npc).get("weapon") or "fists"


def stats(npc: dict) -> dict:
    return WEAPONS.get(weapon(npc), WEAPONS["fists"])


def fighting(state: dict, npc: dict) -> bool:
    fight = active(state)
    return bool(fight) and npc["id"] in fight["attackers"]


def down(npc: dict) -> bool:
    return bool(npc.get("down")) or not npc.get("alive", True)


def _log(state: dict, who: str, kind: str, text: str, now: int, journal: list[dict] | None = None) -> dict:
    """The fight's own log (what the client shows as it happens); the journal gets it too when one is given."""
    fight = state["fight"]
    entry = {"at": now, "who": who, "kind": kind, "text": text, "n": fight.get("count", 0) + 1}
    fight["count"] = entry["n"]
    fight["log"] = (fight["log"] + [entry])[-LOG_KEPT:]
    if journal is not None:
        journal.append({"kind": "fight", "category": kind, "npc_id": who, "reason": text})
    return entry


def start(state: dict, npc_ids: list[str], now: int, why: str) -> dict | None:
    """Bring these people into a fight with the stranger (starting one if needed). Talk is over."""
    people = [n for n in (minds.find(state["npcs"], i) for i in dict.fromkeys(npc_ids)) if n and not down(n)]
    if not people or not state["player"].get("alive", True):
        return active(state)
    fight = state.get("fight") or {"started_at": now, "attackers": [], "swings": {}, "log": [], "count": 0,
                                   "player_ready_at": 0, "why": why}
    state["fight"] = fight
    state["encounter"] = None  # Words are over: no more rounds.
    for npc in people:
        if npc["id"] in fight["attackers"]:
            continue
        fight["attackers"].append(npc["id"])
        minds._set_job(npc, {"kind": "fight", "target": "player", "speed": "run"}, now)
        minds.mind(npc)["facing_player"] = True
        minds.mind(npc)["feelings"]["anger"] = max(minds.mind(npc)["feelings"].get("anger", 0.0), 0.67)
        _log(state, npc["id"], "joins", f"{npc['name']} comes at you with {_their(npc)}!", now)
    ids = set(fight["attackers"])
    state["pending_minds"] = [p for p in state.get("pending_minds", [])
                              if not (p["npc_id"] in ids and p["kind"] in ("decide", "round"))]
    return fight


def responders(state: dict, perceptions: list[dict]) -> list[str]:
    """Who fights at once after the stranger's violence or an unbarred gate: guards who clearly saw it. Anyone else
    decides for themselves (Jev): the smith may pick up her hammer, the merchant runs."""
    ids = []
    for perception in perceptions:
        npc = minds.find(state["npcs"], perception["npc_id"])
        memory = perception["memory"]
        if npc is None or down(npc) or memory["kind"] not in ("violence", "breach") or memory.get("clarity") != "clear":
            continue
        if minds.card(npc).get("guard"):
            ids.append(npc["id"])
    return ids


def gate_held_by(state: dict) -> dict | None:
    """A guard close to the gate steps into the gap and stops anyone walking through an unbarred gate who hasn't
    been let in (D-42): the bar is only half the way in. Dead, downed or distant guards hold nothing."""
    if state.get("admitted"):
        return None
    guards = [g for g in state["npcs"] if minds.card(g).get("guard") and not down(g)
              and math.dist(minds._cell(g), minds.m2.GATEWAY) <= minds.m2.GATE_HOLD_CELLS]
    return min(guards, key=lambda g: math.dist(minds._cell(g), minds.m2.GATEWAY), default=None)


def _their(npc: dict) -> str:
    name = weapon(npc)
    return "bare fists" if name == "fists" else f"a {name}"


def tick(state: dict, npcs: list[dict], elapsed_ms: int, now: int, blocked: set, journal: list[dict]) -> None:
    """The fight over this stretch of time: attackers close in, wind up, and their swings land or miss."""
    fight = active(state)
    if fight is None:
        return
    end = now + elapsed_ms
    here = minds.player_cell(state)
    for npc_id in list(fight["attackers"]):
        npc = minds.find(npcs, npc_id)
        if npc is None or down(npc):
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            continue
        reach = stats(npc)["reach"]
        distance = math.dist(minds._cell(npc), here)
        if distance > GIVE_UP_CELLS:
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            minds._set_job(npc, {"kind": "watch", "until": end + 20_000}, end)
            _log(state, npc_id, "gives_up", f"{npc['name']} gives up the chase.", end, journal)
            continue
        swing = fight["swings"].get(npc_id)
        if swing and end >= swing["lands_at"]:
            _land(state, fight, npc, swing, reach, journal)
            fight["swings"].pop(npc_id, None)
            if not state["player"].get("alive", True):
                break
            continue
        if swing:
            continue  # Mid wind-up: they're committed to the blow.
        if distance > reach:  # Close in at a run.
            controller = npc.get("controller") or {}
            carry = controller.get("step_carry_ms", 0) + elapsed_ms
            while carry >= minds.RUN_STEP_MS and math.dist(minds._cell(npc), here) > reach:
                carry -= minds.RUN_STEP_MS
                step = minds._next_step(minds._cell(npc), here, reach, blocked)
                if step is None:
                    break
                npc["x"], npc["y"] = step
            controller["step_carry_ms"] = carry if math.dist(minds._cell(npc), here) > reach else 0
        if math.dist(minds._cell(npc), here) <= reach and end >= fight.get("recover", {}).get(npc_id, 0):
            fight["swings"][npc_id] = {"started": end, "lands_at": end + stats(npc)["windup_ms"]}
    if not fight["attackers"] or not state["player"].get("alive", True):
        finish(state, end)


def _land(state: dict, fight: dict, npc: dict, swing: dict, reach: float, journal: list[dict]) -> None:
    """The swing lands: a hit if the stranger is still within reach when it does, else a miss."""
    fight.setdefault("recover", {})[npc["id"]] = swing["lands_at"] + RECOVER_MS
    player = state["player"]
    arm = _their(npc)
    if math.dist(minds._cell(npc), minds.player_cell(state)) > reach + 0.01:
        _log(state, npc["id"], "miss", f"You step out of reach and {npc['name']}'s blow cuts the air.",
             swing["lands_at"], journal)
        return
    damage = stats(npc)["damage"]
    health = max(0, player.get("health", 100) - damage)
    player.update(health=health, alive=health > 0)
    wound = f"struck by {npc['name']}'s {weapon(npc)}"
    player.setdefault("injuries", []).append(wound)
    if health <= 0:
        _log(state, npc["id"], "killed", f"{npc['name']} strikes you down with {arm}.", swing["lands_at"], journal)
    else:
        _log(state, npc["id"], "hit", f"{npc['name']} hits you with {arm}. "
                                      + ("You're badly hurt." if health <= 50 else "It hurts."), swing["lands_at"],
             journal)


def punch(state: dict, target_id: str, now: int) -> dict:
    """The stranger's fist: lands if the target is within reach; fixed damage against their armour."""
    fight = active(state)
    npc = minds.find(state["npcs"], target_id)
    if fight is None:
        return {"ok": False, "reason": "There's no fight."}
    if npc is None or down(npc):
        return {"ok": False, "reason": "There's nobody there to hit."}
    if now < fight.get("player_ready_at", 0):
        return {"ok": False, "reason": "You're still recovering from the last swing."}
    fight["player_ready_at"] = now + PUNCH_RECOVER_MS
    if math.dist(minds._cell(npc), minds.player_cell(state)) > ARM_REACH + 0.01:
        _log(state, "player", "miss", f"You swing at {npc['name']} and hit nothing but air.", now,
             state["journal"])
        return {"ok": True, "result": "missed"}
    worn = armor(npc)
    damage = PUNCH[worn]
    if damage == 0:
        _log(state, "player", "glance", f"Your fist thuds uselessly against {npc['name']}'s mail.", now,
             state["journal"])
        return {"ok": True, "result": "glanced"}
    health = max(0, npc.get("health", 100) - damage)
    npc["health"] = health
    npc.setdefault("injuries", []).append("punched by the stranger")
    if health <= DOWN_AT:
        npc["down"] = True
        minds._set_job(npc, None, now)
        (npc.get("controller") or {}).update(activity="down", source="down", path=[])
        fight["attackers"] = [a for a in fight["attackers"] if a != npc["id"]]
        fight["swings"].pop(npc["id"], None)
        _log(state, "player", "down", f"You knock {npc['name']} to the ground. They don't get up.", now,
             state["journal"])
        if not fight["attackers"]:
            finish(state, now)
        return {"ok": True, "result": "down"}
    if npc["id"] not in fight["attackers"]:  # Hit someone who wasn't fighting: now they are.
        start(state, [npc["id"]], now, "punched")
    _log(state, "player", "hit", f"You punch {npc['name']}. " + ("They stagger." if health <= 50 else "They reel."),
         now, state["journal"])
    return {"ok": True, "result": "hit"}


def surrender(state: dict, now: int) -> dict:
    """The stranger gives up: a guard among the attackers arrests them; otherwise they're left be, for now."""
    fight = active(state)
    guard = next((minds.find(state["npcs"], a) for a in (fight or {}).get("attackers", [])
                  if minds.card(minds.find(state["npcs"], a)).get("guard")), None)
    finish(state, now)
    if guard is not None:
        import encounter
        words = encounter.arrest_player(state, guard, now)
        return {"arrested": True, "text": words}
    return {"arrested": False, "text": "They lower their weapons and let you be, for now."}


def finish(state: dict, now: int) -> None:
    fight = active(state)
    if fight is None:
        return
    for npc_id in fight["attackers"]:
        npc = minds.find(state["npcs"], npc_id)
        if npc and not down(npc):
            minds._set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
    state["fight"] = None
