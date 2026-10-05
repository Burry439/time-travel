"""Real-time fights (GDD D-41, D-49): no rounds, no dice, and one set of rules for everyone.

Every blow has a wind-up (from the weapon in hand, data/content/gear.json): it lands after it, and hits only if
the target is still within the weapon's reach and hasn't a raised shield facing it. What it does is gear.hit:
the weapon against the armour covering the spot, how aware the target was, and what follows (bleeding, a
knockout, a broken arm). The stranger fights with whatever is in each hand (Space: right, F: left), throws,
shoots, pours; NPCs fight with the gear they carry. It ends when every attacker is dead, down or gone, when the
stranger gets away, dies, or gives up (guards then arrest them). Everything is recorded in the clock and strike
events, so replay is exact.
"""

from __future__ import annotations

import copy
import math

import cast
import content
import effects
import gear
import paths
import perception
import reputation
import rules
import speech
import tuning
from shapes import Npc, State, Thing

LOG_KEPT = 12
SHIELD_BASH = gear.GEAR["shield_bash"]
COMBAT = gear.GEAR["combat"]
# Kept for older callers and tests.


def active(state: State) -> dict | None:
    return state.get("fight") or None


def stop_fighting(state: State, npc: Npc, now: int) -> None:
    """Carry out the person's own choice to stop, without changing anyone else's intention."""
    fight = active(state)
    if fight:
        fight["attackers"] = [oid for oid in fight["attackers"] if oid != npc["id"]]
        fight["swings"].pop(npc["id"], None)
    npc["guard"] = None
    cast.watch(npc, now, tuning.WATCH_MS)
    if fight and not fight["attackers"]:
        finish(state, now)


def fighting(state: State, npc: Npc) -> bool:
    fight = active(state)
    return bool(fight) and npc["id"] in fight["attackers"]


def down(npc: Npc) -> bool:
    return bool(npc.get("down")) or not npc.get("alive", True)


# --- Who holds what --------------------------------------------------------------------------------------------


def npc_weapon(state: State, npc: Npc) -> dict:
    """What this person fights with: the weapon in their hands, or their fists (never what their card began with)."""
    return gear.weapon(gear.weapon_in_hand(state, npc))


def weapon_name(state: State, npc: Npc) -> str:
    obj = gear.weapon_in_hand(state, npc)
    return obj["name"] if obj else "fists"


def _their(state: State, npc: Npc) -> str:
    name = weapon_name(state, npc)
    return "bare fists" if name == "fists" else f"a {name}"


def hand_use(state: State, hand: str) -> tuple[dict, dict | None]:
    """What the stranger's hand does on its key: (profile, object). Fists when empty, a bash with a shield,
    a pour with a container of water, a throw with anything else that isn't made for fighting."""
    player = state["player"]
    obj = gear.held(state, player, hand)
    if obj is None:
        return gear.weapon(None), None
    record = gear.of(obj)
    if record["kind"] == "shield":
        return dict(SHIELD_BASH, name=obj["name"]), obj
    if obj.get("capacity_l") and obj.get("water_l", 0) > 0:
        return {**gear.weapon(obj), "class": "container", "animation": "pour", "type": "burn"}, obj
    return gear.weapon(obj), obj


def hand_free(state: State, hand: str, person: dict | None = None) -> str | None:
    """Why this hand can't strike now, or None."""
    player = state["player"] if person is None else person
    if not player.get("alive", True) or player.get("down"):
        return "You can't: you're on the ground."
    if effects.limited(player, "hands"):
        return "Your hands aren't free."
    obj = gear.held(state, player, hand)
    kit_id = gear.equipped(player).get(hand)
    if kit_id and obj is None:
        return "That equipment is no longer available to your hand."
    if obj is not None and not gear.functional(obj, shield=gear.of(obj)["kind"] == "shield"):
        return f"The {obj['name']} can't be used in its current condition."
    right = gear.held(state, player, "right")
    if hand == "right" and right is not None and gear.weapon(right)["hands"] == 2:
        left = gear.held(state, player, "left")
        if left is not None and left["id"] != right["id"]:
            return "You need both hands free to use that weapon."
    if right is not None and gear.weapon(right)["hands"] == 2 and gear.limb_useless(player, "arm"):
        return "You can't hold that weapon with both arms."
    if hand == "left" and right is not None and gear.weapon(right)["hands"] == 2:
        return "Both hands are on your weapon: use Space."
    if hand == "left" and gear.limb_useless(player, "arm"):
        return "Your left arm is useless."
    guard = player.get("guard") or {}
    if guard.get("raised") and guard.get("hand") == hand:
        return "That hand is holding your shield up."
    return None


# --- Changes the clock carries (copy-on-write, so a tick's working state never touches the saved one) ---------


def change_object(state: State, object_id: str, **fields) -> None:
    state["objects"][object_id] = {**state["objects"][object_id], **fields}
    state.setdefault("objects_changed", {}).setdefault(object_id, {}).update(fields)


def add_object(state: State, obj: Thing) -> None:
    state["objects"][obj["id"]] = obj
    state.setdefault("objects_added", []).append(obj)


def _log(state: State, who: str, kind: str, text: str, now: int, journal: list[dict] | None = None) -> dict:
    """The fight's own log (what the client shows as it happens); the journal gets it too when one is given."""
    fight = state.get("fight") or {"count": 0, "log": []}  # A blow outside a fight: journal only.
    entry = {"at": now, "who": who, "kind": kind, "text": text, "n": fight.get("count", 0) + 1}
    fight["count"] = entry["n"]
    fight["log"] = (fight["log"] + [entry])[-LOG_KEPT:]
    if journal is not None:
        journal.append({"kind": "fight", "category": kind, "npc_id": who, "reason": text})
    return entry


# --- Starting and ending ---------------------------------------------------------------------------------------


def start(state: State, npc_ids: list[str], now: int, why: str, lethal: bool | None = None) -> dict | None:
    """Bring these people into a fight with the stranger (starting one if needed). Talk is over. They fight to kill
    only after real violence or an assault on the gate they know of (or when told to); otherwise to subdue."""
    people = [n for n in (cast.find(state["npcs"], i) for i in dict.fromkeys(npc_ids)) if n and not down(n)]
    if not people or not state["player"].get("alive", True):
        return active(state)
    fight = state.get("fight") or {"started_at": now, "attackers": [], "swings": {}, "log": [], "count": 0, "why": why}
    if why == "spar":  # A practice bout (the tutorial): nobody means harm, and nobody is arrested (D-50).
        fight["spar"] = True
        fight["health_before"] = {
            "player": state["player"].get("health", 100),  # Its bruises fade after (D-57).
            **{n["id"]: n.get("health", 100) for n in people},
        }
    state["fight"] = fight
    talking = state.get("encounter")  # Those who attack leave the conversation; anyone else can still talk (D-51).
    if talking:
        talking["participants"] = [n for n in talking["participants"] if n not in npc_ids]
        talking["purpose"] = {k: v for k, v in (talking.get("purpose") or {}).items() if k not in npc_ids}
        if not talking["participants"] or any(v != "talk" and v != "joined" for v in talking["purpose"].values()):
            state["encounter"] = None
    for npc in people:
        if npc["id"] in fight["attackers"]:
            continue
        fight["attackers"].append(npc["id"])
        fight.setdefault("gear_seen", {})[npc["id"]] = npc_weapon(state, npc).get("object_id")
        fight.setdefault("lethal", {})[npc["id"]] = reputation.knows_a_crime(npc) if lethal is None else lethal
        cast.set_job(npc, {"kind": "fight", "target": "player", "speed": "run"}, now)
        cast.mind(npc)["facing_player"] = True
        if not fight.get("spar"):  # A practice bout angers nobody: Hal isn't hostile after teaching you (D-59).
            cast.mind(npc)["feelings"]["anger"] = max(cast.mind(npc)["feelings"].get("anger", 0.0), 0.67)
        _log(
            state,
            npc["id"],
            "joins",
            f"{npc['name']} squares up to you with {_their(state, npc)}."
            if fight.get("spar")
            else f"{npc['name']} comes at you with {_their(state, npc)}!"
            if fight["lethal"][npc["id"]]
            else f"{npc['name']} comes after you to put you on the ground!",
            now,
        )
    ids = set(fight["attackers"])
    state["pending_minds"] = [
        p for p in state.get("pending_minds", []) if not (p["npc_id"] in ids and p["kind"] == "decide")
    ]
    return fight


def responders(state: State, perceptions: list[dict]) -> list[str]:
    """Who fights at once after the stranger's violence or an unbarred gate: guards who clearly saw it. Anyone else
    decides for themselves (the decider): the smith may pick up her hammer, the merchant runs."""
    ids = []
    for seen in perceptions:
        npc = cast.find(state["npcs"], seen["npc_id"])
        memory = seen["memory"]
        if npc is None or down(npc) or memory["kind"] not in ("violence", "breach") or memory.get("clarity") != "clear":
            continue
        if cast.card(npc).get("guard"):
            ids.append(npc["id"])
    return ids


def gate_held_by(state: State) -> dict | None:
    """A guard close to the gate steps into the gap and stops anyone walking through an unbarred gate who hasn't
    been let in (D-42): the bar is only half the way in. Dead, downed or distant guards hold nothing."""
    gate = paths.gate(state)
    if state.get("admitted") or gate is None:
        return None
    middle = tuple(gate["middle"])
    guards = [
        g
        for g in state["npcs"]
        if cast.card(g).get("guard") and not down(g) and cast.distance(g, middle) <= tuning.GATE_HOLD_CELLS
    ]
    return min(guards, key=lambda g: cast.distance(g, middle), default=None)


def end_spar(
    state: State, npc: Npc | None, outcome: str, text: str, now: int, journal: list[dict] | None = None
) -> None:
    """A practice bout is over: won, lost or yielded. Nobody is arrested; a good showing earns some respect."""
    _log(
        state, npc["id"] if npc else "player", outcome, text, now, journal if journal is not None else state["journal"]
    )
    if npc is not None:
        view = reputation.regard(npc)
        view["respect"] = round(
            min(1.0, view.get("respect", 0.0) + {"spar_won": 0.15, "spar_lost": 0.05}.get(outcome, 0.0)), 3
        )
    before = (active(state) or {}).get("health_before") or {}
    for who, health in before.items():  # Pulled blows: only bruises, and they fade once it's over (D-57).
        person = state["player"] if who == "player" else cast.find(state["npcs"], who)
        if person is not None and person.get("alive", True):
            person["health"] = max(person.get("health", 100), health)
    finish(state, now)


def finish(state: State, now: int) -> None:
    fight = active(state)
    if fight is None:
        return
    for npc_id in fight["attackers"]:
        npc = cast.find(state["npcs"], npc_id)
        if npc:
            npc["guard"] = None
        if npc and not down(npc):
            cast.watch(npc, now, tuning.WATCH_MS)
    state["fight"] = None


# --- The stranger acts: strike, shoot, throw, pour, guard, swap ------------------------------------------------


def _ahead(state: State, facing: list[float] | None, cells: float) -> list[float]:
    """The spot this many cells in front of the stranger (where a swing or throw at nobody goes)."""
    fx, fy = (facing or [0.0, 1.0])[:2]
    length = math.hypot(fx, fy) or 1.0
    x, y = cast.player_cell(state)
    return [round(x + fx / length * cells, 2), round(y + fy / length * cells, 2)]


def strike(state: State, hand: str, target_id: str | None, now: int, facing: list[float] | None = None) -> dict:
    """Space (right) or F (left): start this hand's blow, shot, throw or pour. It lands after the wind-up, on the
    clock (tick), like anyone's. There is no fighting mode (D-51): anyone can swing at any time. Aimed at nobody,
    the blow goes where the stranger faces and hits whoever is there when it lands. Returns {ok, reason?, swing?}."""
    player = state["player"]
    hand = hand if hand in gear.HAND_SLOTS else "right"
    problem = hand_free(state, hand)
    if problem:
        return {"ok": False, "reason": problem}
    swings = player.setdefault("swings", {})
    if not isinstance(player.get("ready_at"), dict):  # Before D-49 it was one number for the fist.
        player["ready_at"] = {}
    if hand in swings or now < player["ready_at"].get(hand, 0):
        return {"ok": False, "reason": "You're still recovering from the last swing."}
    npc = cast.find(state["npcs"], target_id) if target_id else None
    if npc is not None and not npc.get("alive", True):
        npc = None
    profile, obj = hand_use(state, hand)
    ranged = bool(profile.get("range"))
    if ranged and profile.get("ammo"):
        ammo = state["objects"].get(gear.equipped(player).get("ammo") or "")
        if ammo is None or gear.of(ammo).get("class") != profile["ammo"] or ammo.get("count", 1) <= 0:
            return {"ok": False, "reason": f"You have no {gear.GEAR['ammo'][profile['ammo']]['name']} ready."}
    if ranged and npc is not None and cast.distance(npc, state["player"]) > profile["range"]:
        return {"ok": False, "reason": f"{npc['name']} is out of range."}
    aim = list(cast.cell(npc)) if npc else _ahead(state, facing, profile["range"] if ranged else profile["reach"])
    swing = {
        "hand": hand,
        "target": npc["id"] if npc else None,
        "started": now,
        "lands_at": now + int(profile["windup_ms"]),
        "recover_until": now + int(profile["windup_ms"]) + int(profile["recover_ms"]),
        "animation": profile["animation"],
        "object_id": (obj or {}).get("id"),
        "profile": dict(profile),
        "ranged": ranged,
        "thrown": bool(profile.get("thrown")),
        "aim": aim,
        "facing": _direction(player, npc) if facing is None and npc else list(facing or [0.0, 1.0]),
    }
    fight = active(state) or {}
    if fight.get("spar"):  # A practice bout: the blow is meant for the partner and nobody else (D-57).
        swing["spar_with"] = (fight.get("attackers") or [None])[0]
    swings[hand] = swing
    return {
        "ok": True,
        "swing": swing,
        "profile": {k: profile[k] for k in ("class", "animation", "windup_ms", "reach", "type")},
    }


def throw(state: State, hand: str, target_id: str | None, now: int, facing: list[float] | None = None) -> dict:
    """Throw what's in a hand (a stone, a knife, a javelin): at someone, or as far as it goes the way the stranger
    faces. It leaves the hand."""
    player = state["player"]
    problem = hand_free(state, hand)
    if problem:
        return {"ok": False, "reason": problem}
    ready = player.get("ready_at") or {}
    if hand in (player.get("swings") or {}) or now < (ready.get(hand, 0) if isinstance(ready, dict) else ready):
        return {"ok": False, "reason": "You're still recovering from the last swing."}
    obj = gear.held(state, player, hand)
    npc = cast.find(state["npcs"], target_id) if target_id else None
    if obj is None:
        return {"ok": False, "reason": "You have nothing in that hand to throw."}
    if obj.get("mass_kg", 0) > gear.GEAR["thrown"]["max_mass"]:
        return {"ok": False, "reason": f"The {obj['name']} is too heavy to throw."}
    profile = gear.thrown(obj)
    if npc is not None and cast.distance(npc, state["player"]) > profile["range"]:
        return {"ok": False, "reason": f"{npc['name']} is out of range."}
    aim = list(cast.cell(npc)) if npc else _ahead(state, facing, min(6.0, profile["range"]))
    player.setdefault("swings", {})[hand] = {
        "hand": hand,
        "target": npc["id"] if npc else None,
        "started": now,
        "lands_at": now + int(profile["windup_ms"]),
        "recover_until": now + int(profile["windup_ms"]) + int(profile["recover_ms"]),
        "animation": "throw",
        "object_id": obj["id"],
        "ranged": True,
        "profile": dict(profile),
        "thrown": True,
        "aim": aim,
        "facing": _direction(player, npc) if facing is None and npc else list(facing or [0.0, 1.0]),
    }
    return {"ok": True, "swing": player["swings"][hand]}


def withdraw(state: State, npc_id: str, now: int) -> None:
    """Someone stops attacking the stranger (talked down, or they've made their point); the rest fight on."""
    fight = active(state)
    if fight is None or npc_id not in fight["attackers"]:
        return
    fight["attackers"].remove(npc_id)
    fight["swings"].pop(npc_id, None)
    npc = cast.find(state["npcs"], npc_id)
    if npc is not None and not down(npc):
        cast.watch(npc, now, tuning.WATCH_MS)
        _log(
            state,
            npc_id,
            "stops",
            f"{npc['name']} lowers their {weapon_name(state, npc)} and backs off.",
            now,
            state.get("journal"),
        )
    if not fight["attackers"]:
        finish(state, now)


def guard(state: State, raised: bool, facing: list[float] | None, now: int) -> dict:
    """Hold a shield up (in whichever hand has one), facing a direction; or lower it."""
    player = state["player"]
    shield = next(
        (
            h
            for h in gear.HAND_SLOTS
            if (o := gear.held(state, player, h)) and gear.of(o)["kind"] == "shield" and gear.functional(o, shield=True)
        ),
        None,
    )
    if raised and shield is None:
        return {"ok": False, "reason": "You have no shield in hand."}
    if raised and gear.limb_useless(player, "arm"):
        return {"ok": False, "reason": "Your arm is too hurt to hold a shield up."}
    if raised and (effects.limited(player, "hands") or player.get("down")):
        return {"ok": False, "reason": "Your hands aren't free to guard."}
    if raised and shield in (player.get("swings") or {}):
        return {"ok": False, "reason": "That hand is committed to a blow."}
    before = player.get("guard") or {}
    player["guard"] = (
        {
            "raised": bool(raised),
            "hand": shield,
            "facing": list(facing or [0, 1]),
            "at": before.get("at", now) if before.get("raised") else now,
        }
        if raised
        else None
    )
    return {"ok": True}


def _facing_blow(guard_state: dict, defender: tuple[float, float], attacker: tuple[float, float]) -> bool:
    fx, fy = guard_state.get("facing") or [0, 1]
    dx, dy = attacker[0] - defender[0], attacker[1] - defender[1]
    return fx * dx + fy * dy > 0  # The blow comes from the half the shield faces.


def _direction(actor: dict, target: dict) -> list[float]:
    dx, dy = target["x"] - actor["x"], target["y"] - actor["y"]
    length = math.hypot(dx, dy) or 1.0
    return [dx / length, dy / length]


def _within_arc(actor: dict, target: dict, facing: list | None) -> bool:
    if facing is None:
        return True  # Old saved swings have no direction.
    toward = _direction(actor, target)
    length = math.hypot(*facing) or 1.0
    return (
        cast.distance(actor, target) <= 0.5
        or sum(a * b for a, b in zip(toward, facing)) / length >= COMBAT["facing_dot"]
    )


def _can_block(state: State, person: dict, attacker: dict) -> bool:
    guard_state = person.get("guard") or {}
    shield = gear.held(state, person, guard_state.get("hand", "left"))
    return bool(
        guard_state.get("raised")
        and not person.get("down")
        and not effects.limited(person, "hands")
        and not effects.limited(person, "see")
        and not gear.limb_useless(person, "arm")
        and shield
        and gear.of(shield)["kind"] == "shield"
        and gear.functional(shield, shield=True)
        and _facing_blow(guard_state, cast.cell(person), cast.cell(attacker))
    )


def _parried(person: dict, at: int) -> bool:
    return 0 <= at - (person.get("guard") or {}).get("at", -(10**9)) <= COMBAT["parry_ms"]


# --- On the clock ----------------------------------------------------------------------------------------------


def busy(state: State) -> bool:
    return bool(active(state) or (state["player"].get("swings")) or state.get("projectiles"))


def _npc_hand(state: State, npc: Npc) -> str:
    for hand in gear.HAND_SLOTS:
        obj = gear.held(state, npc, hand)
        if obj and gear.of(obj)["kind"] == "weapon":
            return hand
    return next((h for h in gear.HAND_SLOTS if gear.held(state, npc, h) is None), "right")


def _npc_guard(state: State, fight: dict, npc: Npc, now: int) -> None:
    """A physical response to a seen wind-up, never private knowledge of a concealed weapon."""
    shield = gear.shield_of(state, npc)
    if not shield or not cast.aware(state, npc) or effects.limited(npc, "hands") or effects.limited(npc, "see"):
        npc["guard"] = None
        return
    threat = next(
        (
            s
            for s in (state["player"].get("swings") or {}).values()
            if s["lands_at"] >= now
            and _within_arc(state["player"], npc, s.get("facing"))
            and cast.distance(npc, state["player"]) <= s["profile"]["reach"]
            and not (s.get("object_id") and effects.unseen_by(state["objects"].get(s["object_id"], {}), npc["id"]))
            and paths.line_of_sight(state, cast.cell(npc), cast.player_cell(state))
        ),
        None,
    )
    notices = npc.setdefault("combat_notice", {})
    if threat is None or npc["id"] in fight["swings"]:
        notices.pop(npc["id"], None)
        npc["guard"] = None
        return
    stamp = threat["started"]
    noticed = notices.setdefault(npc["id"], {"swing": stamp, "at": now})
    if noticed["swing"] != stamp:
        noticed.update(swing=stamp, at=now)
    if now - noticed["at"] >= COMBAT["npc_guard_reaction_ms"]:
        hand = next(h for h in gear.HAND_SLOTS if gear.held(state, npc, h) is shield)
        old = npc.get("guard") or {}
        npc["guard"] = {
            "raised": True,
            "hand": hand,
            "facing": _direction(npc, state["player"]),
            "at": old.get("at", now) if old.get("raised") else now,
        }


def _combat_step(state: State, npc: Npc, here: tuple, reach: float, blocked: paths.Grid) -> tuple | None:
    """Choose an available approach or spacing cell. The model already chose the fight's purpose."""
    occupied = {cast.cell(n) for n in state["npcs"] if n["id"] != npc["id"] and not down(n)} | {here}
    x, y = cast.cell(npc)
    neighbors = [(x + dx, y + dy) for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1))]
    choices = [c for c in neighbors if c not in occupied and paths.walkable(c, blocked)]
    distance = cast.distance(npc, here)
    desired = max(1.0, reach * COMBAT["spacing_share"])
    if choices and (distance <= reach or _can_block(state, state["player"], npc)):

        def score(c):
            front = _facing_blow(state["player"].get("guard") or {}, here, c)
            side = 1 if (state["player"].get("guard") or {}).get("raised") and front else 0
            return (side, abs(math.dist(c, here) - desired), c)

        best = min(choices, key=score)
        if score(best)[:2] < score(cast.cell(npc))[:2]:
            return best
        return None
    avoid = paths.Grid(blocked.blocked | frozenset(occupied - {here}), blocked.walk)
    return paths.next_step(cast.cell(npc), here, desired, avoid)


def _reconsider(state: State, npc: Npc, why: str, now: int) -> None:
    cast.add_pending(state, npc["id"], "decide", why)
    cast.mind(npc)["combat_reconsider_at"] = now


def _tick_slice(
    state: State, npcs: list[Npc], elapsed_ms: int, now: int, blocked: paths.Grid, journal: list[dict]
) -> None:
    """This stretch of time: the stranger's blows and missiles land; attackers close in, wind up, and their blows
    land or miss."""
    end = now + elapsed_ms
    fight_before = active(state)
    if state["player"].get("swings"):
        for npc in npcs:
            if not down(npc):
                _npc_guard(state, fight_before or {"swings": {}}, npc, end)
    due = [
        (npc, dict(swing), dict(swing.get("profile") or npc_weapon(state, npc)))
        for oid, swing in list((fight_before or {}).get("swings", {}).items())
        if swing["lands_at"] <= end and (npc := cast.find(npcs, oid)) is not None and not down(npc)
    ]
    alive_before = state["player"].get("alive", True)
    down_before = bool(state["player"].get("down"))
    for npc, swing, profile in due:
        if _bound_weapon(state, npc, swing):
            _npc_lands(state, fight_before, npc, swing, _current_profile(state, npc, swing, profile), journal)
        fight_before["swings"].pop(npc["id"], None)
    alive_after = state["player"].get("alive", True)
    down_after = bool(state["player"].get("down"))
    # Both committed impacts at the same timestamp are eligible from the pre-impact state.
    state["player"]["alive"] = alive_before
    state["player"]["down"] = down_before
    _player_swings(state, npcs, end, journal)
    state["player"]["alive"] = alive_after
    state["player"]["down"] = down_after
    _missiles(state, npcs, end, journal)
    fight = active(state)
    if fight is None:
        return
    here = cast.player_cell(state)
    for npc_id in list(fight["attackers"]):
        npc = cast.find(npcs, npc_id)
        if npc is None or down(npc):
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            continue
        job = cast.mind(npc).get("job") or {}
        if job.get("kind") not in ("fight", "attack"):
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            npc["guard"] = None
            continue  # Their own decision to flee, fetch help or stop is authoritative.
        profile = npc_weapon(state, npc)
        prior_gear = fight.setdefault("gear_seen", {}).get(npc_id)
        if prior_gear and profile.get("object_id") != prior_gear:
            _reconsider(state, npc, "lost their weapon during the fight", end)
        fight["gear_seen"][npc_id] = profile.get("object_id")
        reach = profile["reach"]
        distance = cast.distance(npc, here)
        if distance > tuning.GIVE_UP_CELLS:
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            cast.watch(npc, end, tuning.WATCH_MS)
            _log(state, npc_id, "gives_up", f"{npc['name']} gives up the chase.", end, journal)
            continue
        swing = fight["swings"].get(npc_id)
        if swing and end >= swing["lands_at"]:
            _npc_lands(state, fight, npc, swing, profile, journal)
            fight["swings"].pop(npc_id, None)
            if not state["player"].get("alive", True) or not active(state):
                break  # Dead, or down and caught: it's over.
            continue
        if swing:
            continue  # Mid wind-up: they're committed to the blow.
        _npc_guard(state, fight, npc, end)
        visible = not effects.limited(npc, "see") and paths.line_of_sight(state, cast.cell(npc), here)
        if visible:
            fight.setdefault("last_seen", {})[npc_id] = list(here)
        goal = tuple(fight.get("last_seen", {}).get(npc_id) or cast.cell(npc))
        if not effects.limited(npc, "move") and visible:
            controller = npc.setdefault("controller", {})
            carry = controller.get("step_carry_ms", 0) + elapsed_ms
            while carry >= tuning.RUN_STEP_MS:
                carry -= tuning.RUN_STEP_MS
                step = _combat_step(state, npc, goal, reach, blocked)
                if step is None:
                    break
                npc["x"], npc["y"] = step
                if effects.spring(state, npc, step, end, record=True):
                    break  # Use D-65's world law for combat steps too; newly bound hands cannot wind up.
            controller["step_carry_ms"] = carry
        hand = _npc_hand(state, npc)
        if (
            cast.distance(npc, goal) <= reach
            and (visible or npc_id in fight.get("last_seen", {}))
            and end >= fight.get("recover", {}).get(npc_id, 0)
            and not hand_free(state, hand, npc)
            and not (npc.get("guard") or {}).get("raised")
        ):
            direction = _direction(npc, {"x": goal[0], "y": goal[1]})
            fight["swings"][npc_id] = {
                "profile": dict(profile),
                "object_id": (gear.held(state, npc, hand) or {}).get("id"),
                "hand": hand,
                "facing": direction,
                "started": end,
                "lands_at": end + profile["windup_ms"],
                "recover_until": end + profile["windup_ms"] + profile["recover_ms"],
                "animation": profile["animation"],
            }
    if active(state) and (not fight["attackers"] or not state["player"].get("alive", True)):
        finish(state, end)


def _npc_lands(state: State, fight: dict, npc: Npc, swing: dict, profile: dict, journal: list[dict]) -> None:
    """Their blow lands: a hit if the stranger is still within reach and not behind a raised shield facing it."""
    fight.setdefault("recover", {})[npc["id"]] = swing["lands_at"] + profile["recover_ms"]
    player = state["player"]
    arm = _their(state, npc)
    at = swing["lands_at"]
    here, there = cast.player_cell(state), cast.cell(npc)
    if (
        math.dist(there, here) > profile["reach"] + 0.01
        or not _within_arc(npc, player, swing.get("facing"))
        or not paths.line_of_sight(state, there, here)
    ):
        _log(state, npc["id"], "miss", f"You step out of reach and {npc['name']}'s blow cuts the air.", at, journal)
        return
    guarding = player.get("guard") or {}
    if _can_block(state, player, npc):
        parry = _parried(player, at)
        worn = _wear_shield(state, gear.held(state, player, guarding["hand"]), profile, parry)
        if parry:
            fight["recover"][npc["id"]] += COMBAT["parry_recovery_ms"]
        _log(
            state,
            npc["id"],
            "parried" if parry else "blocked",
            f"You turn {npc['name']}'s blow aside." + worn
            if parry
            else f"{npc['name']}'s blow slams into your shield." + worn,
            at,
            journal,
        )
        return
    if not fight.get("lethal", {}).get(npc["id"], True):  # To subdue, not to kill (D-44).
        blow = min(
            tuning.SUBDUE_DAMAGE, profile.get("damage", tuning.SUBDUE_DAMAGE)
        )  # Bare fists beat you down more slowly.
        health = max(tuning.SUBDUED_AT, player.get("health", 100) - blow)
        player["health"] = health
        player.setdefault("injuries", []).append(f"beaten by {npc['name']}")
        if health > tuning.SUBDUED_AT:
            blunt = f"the butt of {arm}" if profile["type"] in ("cut", "pierce") else arm
            _log(state, npc["id"], "hit", f"{npc['name']} clubs you with {blunt}. You stagger.", at, journal)
            return
        if fight.get("spar"):
            end_spar(
                state,
                npc,
                "spar_lost",
                f'{npc["name"]} knocks you down, then offers you a hand up: "Enough. Not bad for a first time."',
                at,
                journal,
            )
            return
        _log(state, npc["id"], "subdued", f"{npc['name']} knocks you to the ground and pins you there.", at, journal)
        player["down"] = True  # Pinning follows being down; D-65's restraint law.
        state["subdued_by"] = npc["id"]  # store.advance_people carries out the arrest (it touches the world).
        finish(state, at)
        return
    outcome = gear.hit(state, player, profile, aware=True)
    result = gear.apply(player, outcome, at)
    player.setdefault("injuries", []).append(f"struck by {npc['name']}'s {weapon_name(state, npc)}")
    if result == "killed":
        _log(state, npc["id"], "killed", f"{npc['name']} strikes you down with {arm}.", at, journal)
        return
    if result in ("deflected",) or outcome["effective"] < 1:
        _log(state, npc["id"], "glance", f"{npc['name']}'s blow glances off your armour.", at, journal)
        return
    if result in ("knocked_out", "disabled"):  # Down, and they mean to kill: they don't stop.
        _log(state, npc["id"], "hit", f"{npc['name']} beats you to the ground with {arm}.", at, journal)
        return
    bleeding = any(c["kind"] == "bleeding" for c in outcome["conditions"])
    _log(
        state,
        npc["id"],
        "hit",
        f"{npc['name']} hits you with {arm}. "
        + ("You're bleeding." if bleeding else "You're badly hurt." if player["health"] <= 50 else "It hurts."),
        at,
        journal,
    )


def _wear_shield(state: State, shield: dict | None, profile: dict, parry: bool = False) -> str:
    """A blow on a shield wears it; at nothing it splits."""
    if shield is None:
        return ""
    spec = gear.SHIELDS.get(gear.of(shield).get("class") or "improvised", gear.SHIELDS["improvised"])
    wear = profile.get("damage", 10) * gear.GEAR["shield_wear"].get(profile.get("type", "blunt"), 0.5)
    if parry:
        wear *= COMBAT["parry_wear"]
    if any("iron" in m for m in shield.get("materials", [])):
        wear /= gear.GEAR["shield_wear"]["iron_rim"]
    left = round(shield.get("shield_hp", spec["hp"]) - wear, 1)
    if left <= 0:
        change_object(state, shield["id"], shield_hp=0, condition="broken")
        for person in [state["player"]] + state["npcs"]:
            for hand, oid in list(gear.equipped(person).items()):
                if oid == shield["id"]:
                    person["equipped"].pop(hand)
        if (state["player"].get("guard") or {}).get("hand"):
            state["player"]["guard"] = None
        return f" The {shield['name']} splits apart."
    change_object(state, shield["id"], shield_hp=left)
    return ""


def _player_swings(state: State, npcs: list[Npc], end: int, journal: list[dict]) -> None:
    player = state["player"]
    for hand, swing in sorted((player.get("swings") or {}).items(), key=lambda kv: kv[1]["lands_at"]):
        if end < swing["lands_at"]:
            continue
        player["swings"].pop(hand)
        if not player.get("alive", True) or not _bound_weapon(state, player, swing):
            continue
        current = _current_profile(state, player, swing, swing.get("profile") or hand_use(state, hand)[0])
        swing = {**swing, "profile": current}
        if swing.get("ranged"):
            _launch(state, swing)
        else:
            _player_lands(state, npcs, swing, journal)
        current_profile, _ = hand_use(state, hand)
        profile = swing.get("profile") or current_profile
        ready = player.setdefault("ready_at", {})
        ready[hand] = max(ready.get(hand, 0), swing["lands_at"] + int(profile.get("recover_ms", 600)))


def _player_lands(state: State, npcs: list[Npc], swing: dict, journal: list[dict]) -> None:
    """The stranger's blow (or pour) lands on the one they aimed at, if they're still there; a blow aimed at
    nobody lands on whoever is now in front of them within reach, or on thin air."""
    at = swing["lands_at"]
    current_profile, obj = hand_use(state, swing["hand"])
    profile = swing.get("profile") or current_profile
    if swing.get("spar_with"):  # Swung in a practice bout: only ever at the partner, and only while it lasts (D-57).
        if not (active(state) or {}).get("spar"):
            _log(state, "player", "miss", "You check your swing: the bout is over.", at, journal)
            return
        npc = cast.find(npcs, swing["spar_with"])
    else:
        npc = (
            cast.find(npcs, swing["target"])
            if swing.get("target")
            else in_front(state, npcs, swing.get("facing"), profile["reach"])
        )
    if npc is None or not npc.get("alive", True):
        return
    swing["victim_awake"] = not npc.get("down")
    _spar_instead(state, npc, at)
    distance = cast.distance(npc, state["player"])
    if (
        distance > profile["reach"] + 0.01
        or not _within_arc(state["player"], npc, swing.get("facing"))
        or not paths.line_of_sight(state, cast.player_cell(state), cast.cell(npc))
    ):
        _log(state, "player", "miss", f"You swing at {npc['name']} and hit nothing but air.", at, journal)
        _react(state, npc, "missed", swing, at)
        return
    aware = cast.aware(state, npc) or bool(npc.get("woke_at"))
    shield = gear.shield_of(state, npc)
    fight = active(state) or {}
    mid_swing = npc["id"] in (fight.get("swings") or {}) or at < (fight.get("recover") or {}).get(npc["id"], 0)
    if (
        shield is not None
        and aware
        and not mid_swing
        and _can_block(state, npc, state["player"])
        and profile["class"] != "container"
    ):
        parry = _parried(npc, at)
        worn = _wear_shield(state, shield, profile, parry)
        if parry:
            ready = state["player"].setdefault("ready_at", {})
            ready[swing["hand"]] = at + int(profile["recover_ms"]) + COMBAT["parry_recovery_ms"]
        _log(
            state,
            "player",
            "parried" if parry else "blocked",
            f"{npc['name']} takes your blow on the {shield['name']}." + worn,
            at,
            journal,
        )
        _react(state, npc, "deflected", swing, at)
        return
    if profile["class"] == "container":
        outcome = gear.hit(state, npc, profile, family="pour", liquid=obj or {})
        if (obj or {}).get("water_l", 0) > 0:
            effects.put_state(npc, "soaked", "wet from the poured water", [], 30, at, "player")
        change_object(state, obj["id"], water_l=0.0)
    else:
        outcome = gear.hit(state, npc, profile, aware=aware)
    sparring = bool(fight.get("spar")) and npc["id"] in fight.get("attackers", [])
    if sparring:  # Practice: blows are pulled; they bruise, never cut, break or knock anyone out.
        outcome.update(
            effective=min(outcome["effective"], tuning.SPAR_MAX_BLOW),
            conditions=[],
            kill=False,
            down=False,
            knockout=False,
        )
        if outcome["result"] in ("killed", "knocked_out", "disabled"):
            outcome["result"] = "wounded"
    health_before = npc.get("health", 100)
    result = gear.apply(npc, outcome, at)
    if not sparring and not down(npc) and health_before - npc.get("health", 100) >= COMBAT["reconsider_health_step"]:
        _reconsider(state, npc, "hurt in the fight; decide whether to continue, get help or leave", at)
    if sparring and npc.get("health", 100) <= tuning.SPAR_ENOUGH_AT:
        _log(state, "player", "hit", _blow_words(npc, profile, result, outcome), at, journal)
        end_spar(
            state,
            npc,
            "spar_won",
            f'{npc["name"]} steps back and raises a hand: "Enough! Good. Very good."',
            at,
            journal,
        )
        return
    _fell(npc, result, at)
    npc.setdefault("injuries", []).append(f"struck by the stranger's {profile['name']}")
    _log(
        state,
        "player",
        "hit" if result not in ("deflected",) else "glance",
        _blow_words(npc, profile, result, outcome),
        at,
        journal,
    )
    _react(state, npc, result, swing, at)


def _spar_instead(state: State, npc: Npc, at: int) -> None:
    """A blow at someone the scenario has sparring with the stranger (Kade, teaching, D-53) is the bout, not an
    assault: they say so, and it begins (standing for the story's own start of it)."""
    part = rules.role(state, npc).get("spars")
    if not part or active(state) or state.get("fight"):
        return
    rules.note_fired(state, part.get("marks", []))
    speech.say(npc, part["says"], at, state, state["journal"])
    cast.mind(npc).setdefault("talk", []).append({"who": "them", "text": part["says"], "at": at})
    start_spar(state, npc, at, part.get("with"))


def start_spar(state: State, npc: Npc, now: int, weapon_id: str | None = None) -> None:
    """A practice bout with this person (D-50), with their practice weapon in hand if they hold it."""
    weapon = state["objects"].get(weapon_id or "")
    if weapon and weapon.get("holder_id") == npc["id"]:
        npc.setdefault("equipped", {})["right"] = weapon["id"]
    start(state, [npc["id"]], now, "spar", lethal=False)


def in_front(state: State, npcs: list[Npc], facing: list[float] | None, reach: float) -> dict | None:
    """The nearest living person within reach on the side the stranger faces."""
    here = cast.player_cell(state)
    fx, fy = (facing or [0.0, 1.0])[:2]
    length = math.hypot(fx, fy) or 1.0
    best = None
    for npc in npcs:
        there = cast.cell(npc)
        distance = math.dist(there, here)
        if not npc.get("alive", True) or distance > reach + 0.01:
            continue
        if distance > 0.5 and ((there[0] - here[0]) * fx + (there[1] - here[1]) * fy) / (distance * length) < 0.3:
            continue  # Behind or beside them.
        if best is None or distance < best[0]:
            best = (distance, npc)
    return best[1] if best else None


def _blow_words(npc: Npc, profile: dict, result: str, outcome: dict) -> str:
    name, weapon = npc["name"], profile.get("name", "blow")
    if result == "killed":
        return f"Your {weapon} kills {name}."
    if result == "knocked_out":
        return f"You knock {name} senseless. They drop."
    if result == "disabled":
        return f"{name} goes down under your {weapon} and doesn't get up."
    if result == "deflected" or outcome.get("effective", 0) < 1:
        return (
            f"Your {weapon} glances off {name}'s armour."
            if outcome.get("deflected")
            else f"You hit {name}, to no effect."
        )
    bleeding = any(c["kind"] == "bleeding" for c in outcome.get("conditions", []))
    return f"You hit {name} with your {weapon}. " + (
        "They're bleeding." if bleeding else "They stagger." if npc.get("health", 100) <= 50 else "They reel."
    )


def _fell(npc: Npc, result: str, now: int) -> None:
    if result == "killed" or not npc.get("alive", True):
        npc["alive"] = False
        (npc.get("controller") or {}).update(activity="dead", path=[], source="dead")
        if npc.get("mind"):
            npc["mind"]["job"] = None
    elif npc.get("down"):
        cast.set_job(npc, None, now)
        (npc.get("controller") or {}).update(activity="down", source="down", path=[])


def _react(state: State, npc: Npc, result: str, swing: dict, now: int) -> None:
    """In a fight: someone downed drops out; someone hit who wasn't fighting now is. Outside one: an assault that
    everyone who could see it remembers, and answers (D-39, D-41)."""
    if (active(state) or {}).get("spar"):
        return  # Consensual practice is not an assault.
    word = {
        "missed": "missed",
        "deflected": "deflected",
        "blocked": "deflected",
        "wounded": "wounded",
        "knocked_out": "disabled",
        "disabled": "disabled",
        "killed": "killed",
    }.get(result, "wounded")
    harm = {
        "target_id": npc["id"],
        "weapon_id": swing.get("object_id"),
        "method": "melee",
        "injury": "a blow" if word != "missed" else "a swing that missed",
        "result": word,
    }
    entry = {
        "event_id": state.get("event_seq", 0) + 1,
        "category": "success",
        "action": "harm",
        "harm": harm,
        "property": [],
    }
    entry["sim_time_ms"] = now
    before = copy.deepcopy(state)
    victim = cast.find(before["npcs"], npc["id"])
    if swing.get("victim_awake", True):
        victim.update(alive=True, down=False)
    perception.apply_perceptions(state, perception.perceive(state, entry, before))
    fight = active(state)
    if fight is not None:
        if down(npc):
            fight["attackers"] = [a for a in fight["attackers"] if a != npc["id"]]
            fight["swings"].pop(npc["id"], None)
            for other_id in fight["attackers"]:
                other = cast.find(state["npcs"], other_id)
                if (
                    other
                    and paths.line_of_sight(state, cast.cell(other), cast.cell(npc))
                    and not effects.limited(other, "see")
                ):
                    _reconsider(state, other, "saw a person fall in the fight", now)
            if cast.card(npc).get("robs"):
                _robbers_run(state, npc, now)
            if not fight["attackers"]:
                finish(state, now)
        elif (
            result not in ("missed",)
            and npc["id"] not in fight["attackers"]
            and (cast.mind(npc).get("standing_plan") or {}).get("defend")
        ):
            start(state, [npc["id"]], now, "struck")


def _robbers_run(state: State, fallen: Npc, now: int) -> None:
    """Robbers aren't soldiers (D-59): when one of them goes down, the rest give up the hold-up and run."""
    for other in state["npcs"]:
        if other["id"] == fallen["id"] or not cast.card(other).get("robs") or down(other):
            continue
        if not other.get("alive", True) or cast.mind(other).get("stood_aside"):
            continue
        cast.mind(other)["stood_aside"] = True
        fight = active(state)
        if fight and other["id"] in fight["attackers"]:
            fight["attackers"].remove(other["id"])
            fight["swings"].pop(other["id"], None)
        talking = state.get("encounter")
        if talking and other["id"] in talking["participants"]:
            talking["participants"].remove(other["id"])
            (talking.get("purpose") or {}).pop(other["id"], None)
        goal = list(cast.cell(other))
        _, steps = paths.bfs(cast.cell(other), paths.grid(state), 14)
        here = cast.player_cell(state)
        if steps:
            goal = list(max(steps, key=lambda c: (math.dist(c, here), c)))
        cast.set_job(other, {"kind": "flee", "goal": goal, "speed": "run", "until": now + 40_000}, now)
        _log(state, other["id"], "flees", f"{other['name']} breaks and runs.", now, state.get("journal"))


def _launch(state: State, swing: dict) -> None:
    """A shot or throw leaves the hand: a missile flies to where they stood when it was aimed."""
    player = state["player"]
    hand, obj_id = swing["hand"], swing.get("object_id")
    if swing.get("thrown"):
        obj = state["objects"].get(obj_id)
        profile = swing.get("profile") or (gear.thrown(obj) if obj else gear.weapon(None))
        player.setdefault("equipped", {}).pop(hand, None)
        change_object(state, obj_id, holder_id="in_flight")
        flying = obj_id
    else:
        current_profile, _ = hand_use(state, hand)
        profile = swing.get("profile") or current_profile
        ammo_id = gear.equipped(player).get("ammo")
        ammo = gear.worn(state, player, "ammo")
        if ammo is None or ammo.get("count", 1) <= 0 or gear.of(ammo).get("class") != profile.get("ammo"):
            return
        left = ammo.get("count", 1) - 1
        change_object(state, ammo_id, count=left)
        if left <= 0:
            player["equipped"].pop("ammo", None)
            change_object(state, ammo_id, holder_id="spent")
        flying = None
        profile = {**profile, "ammo_from": ammo_id}
    start = cast.player_cell(state)
    aim = _flight_end(state, start, tuple(swing["aim"]))
    flight_ms = int(1000 * math.dist(start, aim) / max(1.0, profile.get("speed") or 15))
    state.setdefault("projectiles", []).append(
        {
            "id": f"shot_{swing['started']}_{hand}",
            "from": list(start),
            "to": list(aim),
            "target": swing["target"],
            "lands_at": swing["lands_at"] + flight_ms,
            "launched_at": swing["lands_at"],
            "object_id": flying,
            "profile": {
                k: profile.get(k)
                for k in ("class", "name", "type", "damage", "edge_hardness", "mass", "ammo", "ammo_from")
            },
        }
    )


def _flight_end(state: State, start: tuple, aim: tuple) -> tuple:
    """The shot lands before the first building, rather than teleporting through it."""
    if paths.line_of_sight(state, tuple(map(round, start)), tuple(map(round, aim))):
        return aim
    last = start
    steps = max(1, math.ceil(math.dist(start, aim) * 2))
    for i in range(1, steps + 1):
        point = tuple(round(a + (b - a) * i / steps) for a, b in zip(start, aim))
        if point in paths.walls(content.level(state)["map"]):
            return last
        last = point
    return last


def _missiles(state: State, npcs: list[Npc], end: int, journal: list[dict]) -> None:
    flying = []
    for shot in state.get("projectiles") or []:
        if end < shot["lands_at"]:
            flying.append(shot)
            continue
        _missile_lands(state, npcs, shot, journal)
    state["projectiles"] = flying


def _missile_lands(state: State, npcs: list[Npc], shot: dict, journal: list[dict]) -> None:
    at, profile = shot["lands_at"], shot["profile"]
    npc = (
        cast.find(npcs, shot["target"])
        if shot.get("target")
        else min(
            (n for n in npcs if n.get("alive", True) and cast.distance(n, tuple(shot["to"])) <= tuning.HIT_RADIUS),
            key=lambda n: cast.distance(n, tuple(shot["to"])),
            default=None,
        )
    )  # Thrown at nobody: whoever is there.
    hit = (
        npc is not None
        and npc.get("alive", True)
        and cast.distance(npc, tuple(shot["to"])) <= tuning.HIT_RADIUS
        and paths.line_of_sight(state, tuple(map(round, shot["from"])), cast.cell(npc))
    )
    landing = tuple(shot["to"])
    if hit:
        victim_awake = not npc.get("down")
        _spar_instead(state, npc, at)
        shield = gear.shield_of(state, npc)
        aware = cast.aware(state, npc)
        if (
            shield is not None
            and _can_block(state, npc, {"x": shot["from"][0], "y": shot["from"][1]})
            and aware
            and gear.SHIELDS.get(gear.of(shield).get("class") or "", {}).get("block_ranged")
        ):
            worn = _wear_shield(state, shield, profile)
            _log(state, "player", "blocked", f"{npc['name']} catches it on the {shield['name']}." + worn, at, journal)
            _react(state, npc, "deflected", {"object_id": shot.get("object_id"), "victim_awake": victim_awake}, at)
        else:
            outcome = gear.hit(state, npc, profile, aware=aware)
            result = gear.apply(npc, outcome, at)
            _fell(npc, result, at)
            _log(state, "player", "hit", _blow_words(npc, profile, result, outcome), at, journal)
            _react(state, npc, result, {"object_id": shot.get("object_id"), "victim_awake": victim_awake}, at)
        landing = cast.cell(npc)
    elif shot.get("target"):
        name = npc["name"] if npc else "them"
        _log(state, "player", "miss", f"Your shot misses {name}.", at, journal)
        if npc is not None:
            _react(state, npc, "missed", {"object_id": shot.get("object_id")}, at)
    x, y = paths.open_cells_near(state, int(landing[0]), int(landing[1]), paths.cleared_obstacles(state), 1)[0]
    if shot.get("object_id"):
        change_object(state, shot["object_id"], holder_id=None, x=x, y=y)
    elif profile.get("ammo_from") and profile.get("ammo") == "arrow":
        source = state["objects"].get(profile["ammo_from"])
        if source is not None:
            spent = {
                **source,
                "id": f"{shot['id']}_arrow",
                "name": "arrow",
                "count": 1,
                "holder_id": None,
                "x": x,
                "y": y,
                "mass_kg": round(source.get("mass_kg", 0.3) / max(1, source.get("count", 1) + 1), 3),
            }
            add_object(state, spent)


def _bound_weapon(state, actor, swing):
    if effects.limited(actor, "hands") or actor.get("down"):
        return False
    if "object_id" not in swing:
        return True  # Compatibility with a hand-built event in old fixtures.
    obj = gear.held(state, actor, swing.get("hand", "right"))
    bound = (obj or {}).get("id") == swing["object_id"] and (
        obj is None or gear.functional(obj, shield=gear.of(obj)["kind"] == "shield")
    )
    if not bound and actor is not state["player"] and fighting(state, actor):
        _reconsider(state, actor, "lost the weapon committed to the blow", swing["lands_at"])
    return bound


def _current_profile(state: State, actor: dict, swing: dict, committed: dict) -> dict:
    """Damage may weaken a committed blow; a repair or replacement never strengthens it midway."""
    obj = gear.held(state, actor, swing.get("hand", "right"))
    if obj is None:
        return committed
    current = gear.thrown(obj) if swing.get("thrown") else gear.weapon(obj)
    return {
        **committed,
        "damage": min(committed["damage"], current["damage"]),
        "type": "blunt" if current["type"] == "blunt" else committed["type"],
        "edge_hardness": min(committed.get("edge_hardness", 0), current.get("edge_hardness", 0)),
    }


def tick(state: State, npcs: list[Npc], elapsed_ms: int, now: int, blocked: paths.Grid, journal: list[dict]) -> None:
    """A single millisecond chronology gives identical events for every clock partition.

    Idle worlds skip this loop. All impacts due at one timestamp use actors eligible before impact;
    movement carries and recovery start at the actual instant, rather than the end of the request.
    """
    if not busy(state):
        return
    _tick_slice(state, npcs, 0, now, blocked, journal)
    import clock

    for at in range(now + 1, now + elapsed_ms + 1):
        if not busy(state):
            clock._bodies(state, npcs, now + elapsed_ms - at + 1, at - 1, journal)
            break
        clock._bodies(state, npcs, 1, at - 1, journal)
        _tick_slice(state, npcs, 1, at - 1, blocked, journal)
