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

import math

import gear
import minds

SUBDUE_DAMAGE = 15  # A spear butt, a fist, a shove to the ground: hurts, doesn't kill (D-44).
SUBDUED_AT = 25  # Beaten down to this, the stranger is at their mercy: a guard arrests them; anyone else stops.
SPAR_ENOUGH_AT = 40  # A sparring partner beaten down to this calls it: "Enough!" (D-50).
SPAR_MAX_BLOW = 12  # Practice blows are pulled: they bruise, never cut or break.
GIVE_UP_CELLS = minds.GIVE_UP_CELLS
LOG_KEPT = 12
HIT_RADIUS = 0.8  # A missile hits someone within this of where it was aimed when it arrives.
SHIELD_BASH = {"class": "shield_bash", "type": "blunt", "damage": 10.0, "reach": 1.3, "windup_ms": 450,
               "recover_ms": 600, "animation": "bash", "edge_hardness": 0.0, "mass": 3.0, "hands": 1,
               "name": "shield"}
# Kept for older callers and tests.
ARM_REACH = gear.WEAPONS["fists"]["reach"]
DOWN_AT = gear.COND["down_at"]


def active(state: dict) -> dict | None:
    return state.get("fight") or None


def fighting(state: dict, npc: dict) -> bool:
    fight = active(state)
    return bool(fight) and npc["id"] in fight["attackers"]


def down(npc: dict) -> bool:
    return bool(npc.get("down")) or not npc.get("alive", True)


# --- Who holds what --------------------------------------------------------------------------------------------

def body(npc: dict) -> dict:
    """A person as gear.hit sees them: what they wear, or (journeys from before seed 10) their card's armour."""
    if npc.get("equipped"):
        return npc
    return {**npc, "card_armour": minds.card(npc).get("armor", "none")}


def npc_weapon(state: dict, npc: dict) -> dict:
    for hand in gear.HAND_SLOTS:
        obj = gear.held(state, npc, hand)
        if obj is not None and gear.of(obj)["kind"] == "weapon":
            return gear.weapon(obj)
    name = minds.card(npc).get("weapon") or "fists"
    cls = gear.LEGACY_WEAPONS.get(name, "fists")
    if cls == "fists":
        return gear.weapon(None)
    spec = gear.WEAPONS[cls]
    stand_in = {"id": None, "name": name, "materials": ["iron", "wood"], "mass_kg": spec.get("ref_mass", 1.5),
                "length_m": None, "flags": ["rigid", "sharp_edge"], "gear": {"kind": "weapon", "class": cls,
                                                                         "covers": [], "quality": "fair"}}
    return {**gear.weapon(stand_in), "name": name}


def weapon_name(state: dict, npc: dict) -> str:
    for hand in gear.HAND_SLOTS:
        obj = gear.held(state, npc, hand)
        if obj is not None and gear.of(obj)["kind"] == "weapon":
            return obj["name"]
    return minds.card(npc).get("weapon") or "fists"


def _their(state: dict, npc: dict) -> str:
    name = weapon_name(state, npc)
    return "bare fists" if name == "fists" else f"a {name}"


def hand_use(state: dict, hand: str) -> tuple[dict, dict | None]:
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


def hand_free(state: dict, hand: str) -> str | None:
    """Why this hand can't strike now, or None."""
    player = state["player"]
    if not player.get("alive", True) or player.get("down"):
        return "You can't: you're on the ground."
    right = gear.held(state, player, "right")
    if hand == "left" and right is not None and gear.of(right)["kind"] == "weapon" and gear.weapon(right)["hands"] == 2:
        return "Both hands are on your weapon: use Space."
    if hand == "left" and gear.limb_useless(player, "arm"):
        return "Your left arm is useless."
    guard = player.get("guard") or {}
    if guard.get("raised") and guard.get("hand") == hand:
        return "That hand is holding your shield up."
    return None


# --- Changes the clock carries (copy-on-write, so a tick's working state never touches the saved one) ---------

def change_object(state: dict, object_id: str, **fields) -> None:
    state["objects"][object_id] = {**state["objects"][object_id], **fields}
    state.setdefault("objects_changed", {}).setdefault(object_id, {}).update(fields)


def add_object(state: dict, obj: dict) -> None:
    state["objects"][obj["id"]] = obj
    state.setdefault("objects_added", []).append(obj)


def _log(state: dict, who: str, kind: str, text: str, now: int, journal: list[dict] | None = None) -> dict:
    """The fight's own log (what the client shows as it happens); the journal gets it too when one is given."""
    fight = state.get("fight") or {"count": 0, "log": []}  # A blow outside a fight: journal only.
    entry = {"at": now, "who": who, "kind": kind, "text": text, "n": fight.get("count", 0) + 1}
    fight["count"] = entry["n"]
    fight["log"] = (fight["log"] + [entry])[-LOG_KEPT:]
    if journal is not None:
        journal.append({"kind": "fight", "category": kind, "npc_id": who, "reason": text})
    return entry


# --- Starting and ending ---------------------------------------------------------------------------------------

def start(state: dict, npc_ids: list[str], now: int, why: str, lethal: bool | None = None) -> dict | None:
    """Bring these people into a fight with the stranger (starting one if needed). Talk is over. They fight to kill
    only after real violence or an assault on the gate they know of (or when told to); otherwise to subdue."""
    people = [n for n in (minds.find(state["npcs"], i) for i in dict.fromkeys(npc_ids)) if n and not down(n)]
    if not people or not state["player"].get("alive", True):
        return active(state)
    fight = state.get("fight") or {"started_at": now, "attackers": [], "swings": {}, "log": [], "count": 0,
                                   "why": why}
    if why == "spar":  # A practice bout (the tutorial): nobody means harm, and nobody is arrested (D-50).
        fight["spar"] = True
        fight["health_before"] = {"player": state["player"].get("health", 100),  # Its bruises fade after (D-57).
                                  **{n["id"]: n.get("health", 100) for n in people}}
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
        fight.setdefault("lethal", {})[npc["id"]] = minds.knows_a_crime(npc) if lethal is None else lethal
        minds._set_job(npc, {"kind": "fight", "target": "player", "speed": "run"}, now)
        minds.mind(npc)["facing_player"] = True
        minds.mind(npc)["feelings"]["anger"] = max(minds.mind(npc)["feelings"].get("anger", 0.0), 0.67)
        _log(state, npc["id"], "joins", f"{npc['name']} squares up to you with {_their(state, npc)}."
             if fight.get("spar") else f"{npc['name']} comes at you with {_their(state, npc)}!"
             if fight["lethal"][npc["id"]] else f"{npc['name']} comes after you to put you on the ground!", now)
    ids = set(fight["attackers"])
    state["pending_minds"] = [p for p in state.get("pending_minds", [])
                              if not (p["npc_id"] in ids and p["kind"] == "decide")]
    return fight


def responders(state: dict, perceptions: list[dict]) -> list[str]:
    """Who fights at once after the stranger's violence or an unbarred gate: guards who clearly saw it. Anyone else
    decides for themselves (the decider): the smith may pick up her hammer, the merchant runs."""
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


def end_spar(state: dict, npc: dict | None, outcome: str, text: str, now: int,
             journal: list[dict] | None = None) -> None:
    """A practice bout is over: won, lost or yielded. Nobody is arrested; a good showing earns some respect."""
    _log(state, npc["id"] if npc else "player", outcome, text, now, journal if journal is not None else state["journal"])
    if npc is not None:
        view = minds.regard(npc)
        view["respect"] = round(min(1.0, view.get("respect", 0.0) + {"spar_won": 0.15, "spar_lost": 0.05}.get(
            outcome, 0.0)), 3)
    before = (active(state) or {}).get("health_before") or {}
    for who, health in before.items():  # Pulled blows: only bruises, and they fade once it's over (D-57).
        person = state["player"] if who == "player" else minds.find(state["npcs"], who)
        if person is not None and person.get("alive", True):
            person["health"] = max(person.get("health", 100), health)
    finish(state, now)


def surrender(state: dict, now: int) -> dict:
    """The stranger gives up: a guard among the attackers arrests them; otherwise they're left be, for now."""
    fight = active(state)
    if fight and fight.get("spar"):
        partner = minds.find(state["npcs"], (fight.get("attackers") or [""])[0])
        name = partner["name"] if partner else "They"
        end_spar(state, partner, "spar_yielded", f"You lower your guard. {name} grins: \"Good enough. You'll learn.\"",
                 now)
        return {"arrested": False, "text": f"{name} lowers the staff and claps you on the shoulder."}
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


# --- The stranger acts: strike, shoot, throw, pour, guard, swap ------------------------------------------------

def _ahead(state: dict, facing: list[float] | None, cells: float) -> list[float]:
    """The spot this many cells in front of the stranger (where a swing or throw at nobody goes)."""
    fx, fy = (facing or [0.0, 1.0])[:2]
    length = math.hypot(fx, fy) or 1.0
    x, y = minds.player_cell(state)
    return [round(x + fx / length * cells, 2), round(y + fy / length * cells, 2)]


def strike(state: dict, hand: str, target_id: str | None, now: int, facing: list[float] | None = None) -> dict:
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
    npc = minds.find(state["npcs"], target_id) if target_id else None
    if npc is not None and not npc.get("alive", True):
        npc = None
    profile, obj = hand_use(state, hand)
    ranged = bool(profile.get("range"))
    if ranged and profile.get("ammo"):
        ammo = state["objects"].get(gear.equipped(player).get("ammo") or "")
        if ammo is None or gear.of(ammo).get("class") != profile["ammo"] or ammo.get("count", 1) <= 0:
            return {"ok": False, "reason": f"You have no {gear.GEAR['ammo'][profile['ammo']]['name']} ready."}
    if ranged and npc is not None and math.dist(minds._cell(npc), minds.player_cell(state)) > profile["range"]:
        return {"ok": False, "reason": f"{npc['name']} is out of range."}
    aim = list(minds._cell(npc)) if npc else _ahead(state, facing, profile["range"] if ranged else profile["reach"])
    swing = {"hand": hand, "target": npc["id"] if npc else None, "started": now,
             "lands_at": now + int(profile["windup_ms"]), "animation": profile["animation"],
             "object_id": (obj or {}).get("id"), "ranged": ranged, "aim": aim, "facing": list(facing or [0.0, 1.0])}
    fight = active(state) or {}
    if fight.get("spar"):  # A practice bout: the blow is meant for the partner and nobody else (D-57).
        swing["spar_with"] = (fight.get("attackers") or [None])[0]
    swings[hand] = swing
    return {"ok": True, "swing": swing, "profile": {k: profile[k] for k in ("class", "animation", "windup_ms",
                                                                              "reach", "type")}}


def throw(state: dict, hand: str, target_id: str | None, now: int, facing: list[float] | None = None) -> dict:
    """Throw what's in a hand (a stone, a knife, a javelin): at someone, or as far as it goes the way the stranger
    faces. It leaves the hand."""
    player = state["player"]
    obj = gear.held(state, player, hand)
    npc = minds.find(state["npcs"], target_id) if target_id else None
    if obj is None:
        return {"ok": False, "reason": "You have nothing in that hand to throw."}
    if obj.get("mass_kg", 0) > gear.GEAR["thrown"]["max_mass"]:
        return {"ok": False, "reason": f"The {obj['name']} is too heavy to throw."}
    profile = gear.thrown(obj)
    if npc is not None and math.dist(minds._cell(npc), minds.player_cell(state)) > profile["range"]:
        return {"ok": False, "reason": f"{npc['name']} is out of range."}
    aim = list(minds._cell(npc)) if npc else _ahead(state, facing, min(6.0, profile["range"]))
    player.setdefault("swings", {})[hand] = {"hand": hand, "target": npc["id"] if npc else None, "started": now,
                                             "lands_at": now + int(profile["windup_ms"]), "animation": "throw",
                                             "object_id": obj["id"], "ranged": True, "thrown": True, "aim": aim}
    return {"ok": True}


def withdraw(state: dict, npc_id: str, now: int) -> None:
    """Someone stops attacking the stranger (talked down, or they've made their point); the rest fight on."""
    fight = active(state)
    if fight is None or npc_id not in fight["attackers"]:
        return
    fight["attackers"].remove(npc_id)
    fight["swings"].pop(npc_id, None)
    npc = minds.find(state["npcs"], npc_id)
    if npc is not None and not down(npc):
        minds._set_job(npc, {"kind": "watch", "until": now + 20_000}, now)
        _log(state, npc_id, "stops", f"{npc['name']} lowers their {weapon_name(state, npc)} and backs off.", now,
             state.get("journal"))
    if not fight["attackers"]:
        finish(state, now)


def guard(state: dict, raised: bool, facing: list[float] | None, now: int) -> dict:
    """Hold a shield up (in whichever hand has one), facing a direction; or lower it."""
    player = state["player"]
    shield = next((h for h in gear.HAND_SLOTS if (o := gear.held(state, player, h)) and gear.of(o)["kind"] == "shield"),
                  None)
    if raised and shield is None:
        return {"ok": False, "reason": "You have no shield in hand."}
    if raised and gear.limb_useless(player, "arm"):
        return {"ok": False, "reason": "Your arm is too hurt to hold a shield up."}
    player["guard"] = {"raised": bool(raised), "hand": shield, "facing": list(facing or [0, 1]), "at": now} if raised else None
    return {"ok": True}


def _facing_blow(guard_state: dict, defender: tuple[float, float], attacker: tuple[float, float]) -> bool:
    fx, fy = guard_state.get("facing") or [0, 1]
    dx, dy = attacker[0] - defender[0], attacker[1] - defender[1]
    return fx * dx + fy * dy > 0  # The blow comes from the half the shield faces.


# --- On the clock ----------------------------------------------------------------------------------------------

def busy(state: dict) -> bool:
    return bool(active(state) or (state["player"].get("swings")) or state.get("projectiles"))


def tick(state: dict, npcs: list[dict], elapsed_ms: int, now: int, blocked: set, journal: list[dict]) -> None:
    """This stretch of time: the stranger's blows and missiles land; attackers close in, wind up, and their blows
    land or miss."""
    end = now + elapsed_ms
    _player_swings(state, npcs, end, journal)
    _missiles(state, npcs, end, journal)
    fight = active(state)
    if fight is None:
        return
    here = minds.player_cell(state)
    for npc_id in list(fight["attackers"]):
        npc = minds.find(npcs, npc_id)
        if npc is None or down(npc):
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            continue
        profile = npc_weapon(state, npc)
        reach = profile["reach"]
        distance = math.dist(minds._cell(npc), here)
        if distance > GIVE_UP_CELLS:
            fight["attackers"].remove(npc_id)
            fight["swings"].pop(npc_id, None)
            minds._set_job(npc, {"kind": "watch", "until": end + 20_000}, end)
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
            fight["swings"][npc_id] = {"started": end, "lands_at": end + profile["windup_ms"],
                                       "animation": profile["animation"]}
    if active(state) and (not fight["attackers"] or not state["player"].get("alive", True)):
        finish(state, end)


def _npc_lands(state: dict, fight: dict, npc: dict, swing: dict, profile: dict, journal: list[dict]) -> None:
    """Their blow lands: a hit if the stranger is still within reach and not behind a raised shield facing it."""
    fight.setdefault("recover", {})[npc["id"]] = swing["lands_at"] + profile["recover_ms"]
    player = state["player"]
    arm = _their(state, npc)
    at = swing["lands_at"]
    here, there = minds.player_cell(state), minds._cell(npc)
    if math.dist(there, here) > profile["reach"] + 0.01:
        _log(state, npc["id"], "miss", f"You step out of reach and {npc['name']}'s blow cuts the air.", at, journal)
        return
    guarding = player.get("guard") or {}
    if guarding.get("raised") and _facing_blow(guarding, here, there):
        worn = _wear_shield(state, gear.held(state, player, guarding["hand"]), profile)
        _log(state, npc["id"], "blocked", f"{npc['name']}'s blow slams into your shield." + worn, at, journal)
        return
    if not fight.get("lethal", {}).get(npc["id"], True):  # To subdue, not to kill (D-44).
        blow = min(SUBDUE_DAMAGE, profile.get("damage", SUBDUE_DAMAGE))  # Bare fists beat you down more slowly.
        health = max(SUBDUED_AT, player.get("health", 100) - blow)
        player["health"] = health
        player.setdefault("injuries", []).append(f"beaten by {npc['name']}")
        if health > SUBDUED_AT:
            blunt = f"the butt of {arm}" if profile["type"] in ("cut", "pierce") else arm
            _log(state, npc["id"], "hit", f"{npc['name']} clubs you with {blunt}. You stagger.", at, journal)
            return
        if fight.get("spar"):
            end_spar(state, npc, "spar_lost", f"{npc['name']} knocks you down, then offers you a hand up: "
                                              f"\"Enough. Not bad for a first time.\"", at, journal)
            return
        _log(state, npc["id"], "subdued", f"{npc['name']} knocks you to the ground and pins you there.", at, journal)
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
    _log(state, npc["id"], "hit", f"{npc['name']} hits you with {arm}. "
         + ("You're bleeding." if bleeding else "You're badly hurt." if player["health"] <= 50 else "It hurts."),
         at, journal)


def _wear_shield(state: dict, shield: dict | None, profile: dict) -> str:
    """A blow on a shield wears it; at nothing it splits."""
    if shield is None:
        return ""
    spec = gear.SHIELDS.get(gear.of(shield).get("class") or "improvised", gear.SHIELDS["improvised"])
    wear = profile.get("damage", 10) * gear.GEAR["shield_wear"].get(profile.get("type", "blunt"), 0.5)
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


def _player_swings(state: dict, npcs: list[dict], end: int, journal: list[dict]) -> None:
    player = state["player"]
    for hand, swing in sorted((player.get("swings") or {}).items(), key=lambda kv: kv[1]["lands_at"]):
        if end < swing["lands_at"]:
            continue
        player["swings"].pop(hand)
        if not player.get("alive", True):
            continue
        if swing.get("ranged"):
            _launch(state, swing)
        else:
            _player_lands(state, npcs, swing, journal)
        profile, _ = hand_use(state, hand)
        player.setdefault("ready_at", {})[hand] = swing["lands_at"] + int(profile.get("recover_ms", 600))


def _player_lands(state: dict, npcs: list[dict], swing: dict, journal: list[dict]) -> None:
    """The stranger's blow (or pour) lands on the one they aimed at, if they're still there; a blow aimed at
    nobody lands on whoever is now in front of them within reach, or on thin air."""
    at = swing["lands_at"]
    profile, obj = hand_use(state, swing["hand"])
    if swing.get("spar_with"):  # Swung in a practice bout: only ever at the partner, and only while it lasts (D-57).
        if not (active(state) or {}).get("spar"):
            _log(state, "player", "miss", "You check your swing: the bout is over.", at, journal)
            return
        npc = minds.find(npcs, swing["spar_with"])
    else:
        npc = minds.find(npcs, swing["target"]) if swing.get("target") else in_front(state, npcs, swing.get("facing"),
                                                                                      profile["reach"])
    if npc is None or not npc.get("alive", True):
        return
    _spar_instead(state, npc, at)
    distance = math.dist(minds._cell(npc), minds.player_cell(state))
    if distance > profile["reach"] + 0.01:
        _log(state, "player", "miss", f"You swing at {npc['name']} and hit nothing but air.", at, journal)
        _react(state, npc, "missed", swing, at)
        return
    import crafting
    aware = crafting._aware(state, npc) or bool(npc.get("woke_at"))
    shield = gear.shield_of(state, npc)
    fight = active(state) or {}
    mid_swing = npc["id"] in (fight.get("swings") or {}) or at < (fight.get("recover") or {}).get(npc["id"], 0)
    if shield is not None and aware and not npc.get("down") and not mid_swing and profile["class"] != "container":
        worn = _wear_shield(state, shield, profile)
        _log(state, "player", "blocked", f"{npc['name']} takes your blow on the {shield['name']}." + worn, at, journal)
        _react(state, npc, "deflected", swing, at)
        return
    if profile["class"] == "container":
        outcome = gear.hit(state, body(npc), profile, family="pour", liquid=obj or {})
        change_object(state, obj["id"], water_l=0.0)
    else:
        outcome = gear.hit(state, body(npc), profile, aware=aware)
    sparring = bool(fight.get("spar")) and npc["id"] in fight.get("attackers", [])
    if sparring:  # Practice: blows are pulled; they bruise, never cut, break or knock anyone out.
        outcome.update(effective=min(outcome["effective"], SPAR_MAX_BLOW), conditions=[], kill=False, down=False,
                       knockout=False)
        if outcome["result"] in ("killed", "knocked_out", "disabled"):
            outcome["result"] = "wounded"
    result = gear.apply(npc, outcome, at)
    if sparring and npc.get("health", 100) <= SPAR_ENOUGH_AT:
        _log(state, "player", "hit", _blow_words(npc, profile, result, outcome), at, journal)
        end_spar(state, npc, "spar_won", f"{npc['name']} steps back and raises a hand: \"Enough! Good. "
                                         f"Very good.\"", at, journal)
        return
    _fell(npc, result, at)
    npc.setdefault("injuries", []).append(f"struck by the stranger's {profile['name']}")
    _log(state, "player", "hit" if result not in ("deflected",) else "glance", _blow_words(npc, profile, result, outcome),
         at, journal)
    _react(state, npc, result, swing, at)


def _spar_instead(state: dict, npc: dict, at: int) -> None:
    """In the tutorial, a blow at Kade while he's teaching is the bout, not an assault (D-53)."""
    if state.get("tutorial") and not active(state):
        import tutorial
        tutorial.spar_now(state, npc, at)


def in_front(state: dict, npcs: list[dict], facing: list[float] | None, reach: float) -> dict | None:
    """The nearest living person within reach on the side the stranger faces."""
    here = minds.player_cell(state)
    fx, fy = (facing or [0.0, 1.0])[:2]
    length = math.hypot(fx, fy) or 1.0
    best = None
    for npc in npcs:
        there = minds._cell(npc)
        distance = math.dist(there, here)
        if not npc.get("alive", True) or distance > reach + 0.01:
            continue
        if distance > 0.5 and ((there[0] - here[0]) * fx + (there[1] - here[1]) * fy) / (distance * length) < 0.3:
            continue  # Behind or beside them.
        if best is None or distance < best[0]:
            best = (distance, npc)
    return best[1] if best else None


def _blow_words(npc: dict, profile: dict, result: str, outcome: dict) -> str:
    name, weapon = npc["name"], profile.get("name", "blow")
    if result == "killed":
        return f"Your {weapon} kills {name}."
    if result == "knocked_out":
        return f"You knock {name} senseless. They drop."
    if result == "disabled":
        return f"{name} goes down under your {weapon} and doesn't get up."
    if result == "deflected" or outcome.get("effective", 0) < 1:
        return (f"Your {weapon} glances off {name}'s armour." if outcome.get("deflected")
                else f"You hit {name}, to no effect.")
    bleeding = any(c["kind"] == "bleeding" for c in outcome.get("conditions", []))
    return f"You hit {name} with your {weapon}. " + ("They're bleeding." if bleeding else
                                                       "They stagger." if npc.get("health", 100) <= 50 else "They reel.")


def _fell(npc: dict, result: str, now: int) -> None:
    if result == "killed" or not npc.get("alive", True):
        npc["alive"] = False
        (npc.get("controller") or {}).update(activity="dead", path=[], source="dead")
        if npc.get("mind"):
            npc["mind"]["job"] = None
    elif npc.get("down"):
        minds._set_job(npc, None, now)
        (npc.get("controller") or {}).update(activity="down", source="down", path=[])


def _react(state: dict, npc: dict, result: str, swing: dict, now: int) -> None:
    """In a fight: someone downed drops out; someone hit who wasn't fighting now is. Outside one: an assault that
    everyone who could see it remembers, and answers (D-39, D-41)."""
    fight = active(state)
    if fight is not None:
        if down(npc):
            fight["attackers"] = [a for a in fight["attackers"] if a != npc["id"]]
            fight["swings"].pop(npc["id"], None)
            if not fight["attackers"]:
                finish(state, now)
        elif result not in ("missed",) and npc["id"] not in fight["attackers"]:
            start(state, [npc["id"]], now, "struck")
        return
    word = {"missed": "missed", "deflected": "deflected", "blocked": "deflected", "wounded": "wounded",
            "knocked_out": "disabled", "disabled": "disabled", "killed": "killed"}.get(result, "wounded")
    harm = {"target_id": npc["id"], "weapon_id": swing.get("object_id"), "method": "melee",
            "injury": "a blow" if word != "missed" else "a swing that missed", "result": word}
    entry = {"event_id": state.get("event_seq", 0) + 1, "category": "success", "action": "harm", "harm": harm,
             "property": []}
    minds.apply_perceptions(state, minds.perceive(state, entry))


def _launch(state: dict, swing: dict) -> None:
    """A shot or throw leaves the hand: a missile flies to where they stood when it was aimed."""
    player = state["player"]
    hand, obj_id = swing["hand"], swing.get("object_id")
    if swing.get("thrown"):
        obj = state["objects"].get(obj_id)
        profile = gear.thrown(obj) if obj else gear.weapon(None)
        player.setdefault("equipped", {}).pop(hand, None)
        change_object(state, obj_id, holder_id="in_flight")
        flying = obj_id
    else:
        profile, _ = hand_use(state, hand)
        ammo_id = gear.equipped(player).get("ammo")
        ammo = state["objects"].get(ammo_id or "")
        if ammo is None:
            return
        left = ammo.get("count", 1) - 1
        change_object(state, ammo_id, count=left)
        if left <= 0:
            player["equipped"].pop("ammo", None)
            change_object(state, ammo_id, holder_id="spent")
        flying = None
        profile = {**profile, "ammo_from": ammo_id}
    start = minds.player_cell(state)
    aim = tuple(swing["aim"])
    flight_ms = int(1000 * math.dist(start, aim) / max(1.0, profile.get("speed") or 15))
    state.setdefault("projectiles", []).append({
        "id": f"shot_{swing['started']}_{hand}", "from": list(start), "to": list(aim), "target": swing["target"],
        "lands_at": swing["lands_at"] + flight_ms, "launched_at": swing["lands_at"], "object_id": flying,
        "profile": {k: profile.get(k) for k in ("class", "name", "type", "damage", "edge_hardness", "mass",
                                                "ammo", "ammo_from")}})


def _missiles(state: dict, npcs: list[dict], end: int, journal: list[dict]) -> None:
    flying = []
    for shot in state.get("projectiles") or []:
        if end < shot["lands_at"]:
            flying.append(shot)
            continue
        _missile_lands(state, npcs, shot, journal)
    state["projectiles"] = flying


def _missile_lands(state: dict, npcs: list[dict], shot: dict, journal: list[dict]) -> None:
    import crafting
    at, profile = shot["lands_at"], shot["profile"]
    npc = minds.find(npcs, shot["target"]) if shot.get("target") else min(
        (n for n in npcs if n.get("alive", True) and math.dist(minds._cell(n), tuple(shot["to"])) <= HIT_RADIUS),
        key=lambda n: math.dist(minds._cell(n), tuple(shot["to"])), default=None)  # Thrown at nobody: whoever is there.
    hit = npc is not None and npc.get("alive", True) and math.dist(minds._cell(npc), tuple(shot["to"])) <= HIT_RADIUS
    landing = tuple(shot["to"])
    if hit:
        _spar_instead(state, npc, at)
        shield = gear.shield_of(state, npc)
        aware = crafting._aware(state, npc)
        if shield is not None and aware and gear.SHIELDS.get(gear.of(shield).get("class") or "", {}).get("block_ranged"):
            worn = _wear_shield(state, shield, profile)
            _log(state, "player", "blocked", f"{npc['name']} catches it on the {shield['name']}." + worn, at, journal)
            _react(state, npc, "deflected", {"object_id": shot.get("object_id")}, at)
        else:
            outcome = gear.hit(state, body(npc), profile, aware=aware)
            result = gear.apply(npc, outcome, at)
            _fell(npc, result, at)
            _log(state, "player", "hit", _blow_words(npc, profile, result, outcome), at, journal)
            _react(state, npc, result, {"object_id": shot.get("object_id")}, at)
        landing = minds._cell(npc)
    elif shot.get("target"):
        name = npc["name"] if npc else "them"
        _log(state, "player", "miss", f"Your shot misses {name}.", at, journal)
        if npc is not None:
            _react(state, npc, "missed", {"object_id": shot.get("object_id")}, at)
    x, y = crafting._open_cells_near(state, int(landing[0]), int(landing[1]), crafting.cleared_obstacles(state), 1)[0]
    if shot.get("object_id"):
        change_object(state, shot["object_id"], holder_id=None, x=x, y=y)
    elif profile.get("ammo_from") and profile.get("ammo") == "arrow":
        source = state["objects"].get(profile["ammo_from"])
        if source is not None:
            spent = {**source, "id": f"{shot['id']}_arrow", "name": "arrow", "count": 1, "holder_id": None,
                     "x": x, "y": y, "mass_kg": round(source.get("mass_kg", 0.3) / max(1, source.get("count", 1) + 1), 3)}
            add_object(state, spent)
