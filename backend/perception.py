"""What people see of what the stranger does: who could see it and how clearly, the memory each takes away,
and the moment itself (they turn, they're angry or afraid, the nearest shouts), decided by code. What they
then choose to do is the decider's (minds.py)."""

from __future__ import annotations

import cast
import m2
import paths
import reputation
import speech
import tuning


def _describe(state: dict, entry: dict) -> list[dict]:
    """What onlookers could see of a committed attempt, clearly and from afar: one view per notable thing.

    Violence and theft make people think about what to do; seeing something shown or given is only
    remembered (it counts as evidence about the stranger when they next talk).
    """
    names = {n["id"]: n["name"] for n in state["npcs"]}
    if entry.get("category") not in ("success", "partial_success"):
        return []
    views = []
    harm = entry.get("harm")
    if isinstance(harm, dict):
        victim = names.get(harm["target_id"], "someone")
        weapon = state["objects"].get(harm.get("weapon_id") or "", {}).get("name")
        how = f" with a {weapon}" if weapon else " with bare hands"
        verb = "threw a " + weapon + " at" if harm.get("method") == "thrown" and weapon else "attacked"
        poured = harm.get("method") == "poured"
        verb = "threw water over" if poured else verb
        verb = "strangled" if harm.get("family") == "choke" else verb
        outcome = {
            "killed": f"{victim} fell and did not get up.",
            "wounded": f"{victim} was hurt.",
            "disabled": f"{victim} went down, badly hurt, and could not fight on.",
            "knocked_out": f"{victim} dropped senseless.",
            "deflected": f"The blow glanced off {victim}'s armour.",
            "missed": f"{victim} was soaked." if poured else f"The blow missed {victim}.",
        }[harm["result"]]
        short = {
            "killed": f"killed {victim}",
            "disabled": f"struck down {victim}",
            "knocked_out": f"knocked {victim} senseless",
        }.get(harm["result"], f"attacked {victim}")
        severity = {"killed": 3, "wounded": 2, "disabled": 3, "knocked_out": 3, "deflected": 1, "missed": 1}[
            harm["result"]
        ]
        views.append(
            {
                "kind": "violence",
                "victim": harm["target_id"],
                "clear": {
                    "summary": f"The stranger {verb} {victim}{'' if 'threw' in verb else how}. {outcome}",
                    "short": short,
                    "severity": severity,
                },
                "vague": {
                    "summary": (
                        f"There was a scuffle near the stranger and {victim} went down."
                        if harm["result"] in ("killed", "disabled", "knocked_out")
                        else f"There was a scuffle near the stranger; {victim} cried out."
                    ),
                    "short": f"was in a fight with {victim}",
                    "severity": max(1, severity - 1),
                },
            }
        )
    claims = [c for c in entry.get("property") or [] if c.get("how") != "used"]  # Using isn't taking (D-46).
    if claims and not isinstance(harm, dict):  # A weapon grabbed for an attack is part of the attack.
        claim = claims[0]
        owner = names.get(claim["owner_id"], "someone")
        verb = {
            "taken": "took",
            "used up": "used up",
            "used": "used",
            "given away": "gave away",
            "gathered from": "took some of",
        }.get(claim["how"], f"{claim['how']}")
        views.append(
            {
                "kind": "theft",
                "victim": claim["owner_id"],
                "item": claim["name"],
                "clear": {
                    "summary": f"The stranger {verb} {owner}'s {claim['name']} without asking.",
                    "short": f"stole {owner}'s {claim['name']}",
                    "severity": 2,
                },
                "vague": {
                    "summary": f"The stranger was handling {owner}'s things.",
                    "short": f"was handling {owner}'s things",
                    "severity": 1,
                },
            }
        )
    shown = entry.get("demonstration")
    if isinstance(shown, dict):
        views.append(
            {
                "kind": "demonstration",
                "victim": None,
                "item": shown["object_name"],
                "audience": shown.get("audience_ids", []),
                "think": False,
                "works": shown["works"],
                "wonder": shown.get("wonder", "ordinary"),
                "clear": {"summary": shown["observed"], "short": f"showed off a {shown['object_name']}", "severity": 1},
                "vague": {
                    "summary": "The stranger was showing people something; it was hard to see what.",
                    "short": "was showing something",
                    "severity": 0,
                },
            }
        )
    made = entry.get("made_ids") or []
    if (
        made
        and not isinstance(shown, dict)
        and entry.get("category") in ("success", "partial_success")
        and not isinstance(entry.get("harm"), dict)
    ):  # Watching something being made is being shown it (D-54).
        name = entry.get("made_name") or "something"
        views.append(
            {
                "kind": "demonstration",
                "victim": None,
                "item": name,
                "audience": [],
                "think": False,
                "works": True,
                "wonder": "ordinary",
                "clear": {
                    "summary": f"The stranger made a {name} in front of them: {entry.get('reason', '')}",
                    "short": f"made a {name}",
                    "severity": 1,
                },
                "vague": {
                    "summary": "The stranger was making something; it was hard to see what.",
                    "short": "was making something",
                    "severity": 0,
                },
            }
        )
    placed = entry.get("install")
    if isinstance(placed, dict):
        aids = f" using the {' and the '.join(placed['aid_names'])}" if placed["aid_names"] else ""
        views.append(
            {
                "kind": "demonstration",
                "victim": None,
                "item": placed["object_name"],
                "think": False,
                "works": True,
                "audience": [],
                "clear_cells": tuning.SIGHT_CELLS,  # A beam going up: anyone can see it.
                "clear": {
                    "summary": f"The stranger got the {placed['object_name']} up into the {placed['into_name']}{aids}.",
                    "short": f"put the {placed['object_name']} in place",
                    "severity": 1,
                },
                "vague": {
                    "summary": "The stranger was heaving something heavy into place.",
                    "short": "was working on something heavy",
                    "severity": 0,
                },
            }
        )
    lifted = entry.get("lift_out")
    if isinstance(lifted, dict):
        aids = f" using the {' and the '.join(lifted['aid_names'])}" if lifted["aid_names"] else ""
        if lifted["from_id"] == m2.GATE_FIXTURE and not gate_work_agreed(state):
            views.append(
                {
                    "kind": "breach",
                    "victim": None,
                    "item": lifted["object_name"],
                    "clear_cells": tuning.SIGHT_CELLS,
                    "clear": {
                        "summary": f"The stranger lifted the {lifted['object_name']} off the city gate"
                        f"{aids}: the gate is unbarred.",
                        "short": "unbarred the city gate",
                        "severity": 3,
                    },
                    "vague": {
                        "summary": "The stranger was doing something at the gate.",
                        "short": "was meddling at the gate",
                        "severity": 2,
                    },
                }
            )
        else:  # Work someone asked for (Tomas's swap): seen, not feared.
            views.append(
                {
                    "kind": "demonstration",
                    "victim": None,
                    "item": lifted["object_name"],
                    "think": False,
                    "works": True,
                    "audience": [],
                    "clear_cells": tuning.SIGHT_CELLS,
                    "clear": {
                        "summary": f"The stranger got the {lifted['object_name']} out of the "
                        f"{lifted['from_name']}{aids}.",
                        "short": f"took the {lifted['object_name']} down",
                        "severity": 1,
                    },
                    "vague": {
                        "summary": "The stranger was heaving something heavy down.",
                        "short": "was working on something heavy",
                        "severity": 0,
                    },
                }
            )
    give = entry.get("give")
    if isinstance(give, dict):
        things = " and ".join(give["names"])
        views.append(
            {
                "kind": "gift",
                "victim": give["recipient_id"],
                "item": things,
                "think": False,
                "clear": {
                    "summary": f"The stranger gave {give['recipient_name']} a {things}.",
                    "short": f"gave {give['recipient_name']} a {things}",
                    "severity": 1,
                },
                "vague": {
                    "summary": f"The stranger handed something to {give['recipient_name']}.",
                    "short": f"handed something to {give['recipient_name']}",
                    "severity": 0,
                },
            }
        )
    treated = entry.get("treated")
    if isinstance(treated, dict):  # Binding someone's wound, splinting a limb (D-49): help, seen and remembered.
        views.append(
            {
                "kind": "help",
                "victim": treated["patient_id"],
                "item": treated["remedy"],
                "think": False,
                "clear": {
                    "summary": f"The stranger treated {treated['patient_name']}'s {treated['what']} "
                    f"with a {treated['remedy']}.",
                    "short": f"treated {treated['patient_name']}'s wound",
                    "severity": 1,
                },
                "vague": {
                    "summary": f"The stranger was tending to {treated['patient_name']}.",
                    "short": f"tended to {treated['patient_name']}",
                    "severity": 0,
                },
            }
        )
    return views


SOURCES = {"violence": "victim", "theft": "victim", "gift": "received", "help": "received"}


def gate_work_agreed(state: dict) -> bool:
    """The stranger has an accepted deal to put a new bar on the gate (Tomas's swap): taking the old one out is
    that work, not an assault on the gate."""
    for deal in (state.get("agreements") or {}).values():
        if deal.get("status") != "accepted":
            continue
        issuer = cast.find(state["npcs"], deal.get("issuer") or "")
        offer = next(
            (o for o in (cast.card(issuer).get("offers", []) if issuer else []) if o["id"] == deal.get("template")),
            {},
        )
        if (offer.get("done_when") or {}).get("installed"):
            return True
    return False


def perceive(state: dict, entry: dict) -> list[dict]:
    """Memories for everyone who could see what the player just did (and for the people it involved).

    Close witnesses see what happened; those further off only see something going on.
    """
    here = cast.player_cell(state)
    perceptions = []
    for seen in _describe(state, entry):
        victim = cast.find(state["npcs"], seen["victim"] or "")
        involved = {seen["victim"], *seen.get("audience", [])} - {None}
        for npc in state["npcs"]:
            if not npc.get("alive", True) or npc.get("down"):
                continue  # The dead and the knocked-down see nothing.
            views = []
            if cast.distance(npc, here) <= tuning.SIGHT_CELLS and paths.line_of_sight(cast.cell(npc), here):
                views.append(cast.distance(npc, here))
            if (
                victim is not None
                and cast.distance(npc, victim) <= tuning.SIGHT_CELLS
                and paths.line_of_sight(cast.cell(npc), cast.cell(victim))
            ):
                views.append(cast.distance(npc, victim))
            close = npc["id"] in involved
            if not (close or views):
                continue
            clarity = "clear" if close or min(views) <= seen.get("clear_cells", tuning.CLEAR_VIEW_CELLS) else "vague"
            source = (
                SOURCES.get(seen["kind"], "shown") if npc["id"] == seen["victim"] else "shown" if close else "witnessed"
            )
            memory = {
                "kind": seen["kind"],
                "victim": seen["victim"],
                "item": seen.get("item"),
                **seen[clarity],
                "clarity": clarity,
                "at": state["sim_time_ms"],
                "event": entry.get("event_id"),
                "source": source,
            }
            if "works" in seen:
                memory["works"] = seen["works"]
            if seen.get("wonder") and clarity == "clear":
                memory["wonder"] = seen["wonder"]
            if npc["id"] == seen["victim"]:  # They tell it in the first person: "attacked me", "stole my plank".
                memory["short"] = memory["short"].replace(f"{npc['name']}'s", "my").replace(npc["name"], "me")
            perceptions.append({"npc_id": npc["id"], "memory": memory, "think": seen.get("think", True)})
    return perceptions


def apply_perceptions(state: dict, perceptions: list[dict]) -> None:
    """Remember what was seen; people who clearly saw a crime react at once by code (they turn, they're angry
    or afraid, the nearest one shouts), and then decide what to do about it (the decider)."""
    barked = False
    here = cast.player_cell(state)
    order = sorted(
        perceptions,
        key=lambda p: (
            -p["memory"]["severity"],
            p["memory"]["source"] != "victim",
            cast.distance(cast.find(state["npcs"], p["npc_id"]) or {"x": 0, "y": 0}, here),
        ),
    )
    for perception in order:
        npc = cast.find(state["npcs"], perception["npc_id"])
        if npc is None or not npc.get("alive", True):
            continue
        memory = perception["memory"]
        reputation.remember(npc, memory)
        if perception.get("think", True):
            cast.mind(npc)["rethinks"] = 0
            cast.add_pending(state, npc["id"], "decide", memory["source"])
        if memory["kind"] in reputation.CRIME_KINDS and memory.get("clarity") == "clear":
            barked = _react_at_once(state, npc, memory, barked) or barked
    # Violence clearly seen: guards (and an armed victim still standing) fight at once (D-41). Imported here because
    # combat imports this module (a blow is seen like any deed).
    import combat

    fighters = combat.responders(state, perceptions)
    if fighters and state["player"].get("alive", True):
        combat.start(state, fighters, state["sim_time_ms"], "violence")


def _react_at_once(state: dict, npc: dict, memory: dict, barked: bool) -> bool:
    """The moment itself, decided by code: face the stranger, feel it, and (the nearest) shout."""
    feelings, victim = cast.mind(npc)["feelings"], memory.get("victim") == npc["id"]
    guard = cast.card(npc).get("guard")
    if memory["kind"] == "theft":
        feelings["anger"] = max(feelings.get("anger", 0.0), 0.67 if victim else 0.34)
    elif guard or victim and cast.armed_with(state, npc):
        feelings["anger"] = max(feelings.get("anger", 0.0), 0.67)
    else:
        feelings["fear"] = max(feelings.get("fear", 0.0), 0.67)
    distance = cast.distance(npc, state["player"])
    cast.mind(npc)["facing_player"] = distance <= tuning.AMBIENT_CELLS * 1.5
    # The moment's feelings hold for a while, whatever is decided next.
    cast.mind(npc)["stirred"] = {
        "until": state["sim_time_ms"] + tuning.STIRRED_MS,
        "fear": feelings.get("fear", 0.0),
        "anger": feelings.get("anger", 0.0),
    }
    if barked or distance > tuning.BARK_CELLS:
        return False
    tone = {
        ("theft", True): "theft",
        ("theft", False): "theft_witness",
        ("breach", False): "breach",
        ("violence", True): "violence_victim",
        ("violence", False): "violence",
    }[(memory["kind"], victim)]
    bank = speech.LINES.get("caught", {}).get(tone) or []
    if not bank:
        return False
    words = speech.slots(state, npc)
    text = bank[(len(cast.mind(npc)["memories"]) + len(npc["id"])) % len(bank)].format(**words)
    speech.say(npc, text, state["sim_time_ms"], state, [], f"caught.{tone}")
    return True
