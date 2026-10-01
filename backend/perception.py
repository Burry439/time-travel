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
from shapes import Memory, Npc, State


def _describe(state: State, entry: dict) -> list[dict]:
    """What onlookers could see of a committed attempt, clearly and from afar: one view per notable thing.

    Violence and theft make people think about what to do; seeing something shown or given is only
    remembered (it counts as evidence about the stranger when they next talk).
    """
    if entry.get("category") not in ("success", "partial_success"):
        return []
    names = {n["id"]: n["name"] for n in state["npcs"]}
    harm = entry.get("harm") if isinstance(entry.get("harm"), dict) else None
    shown = entry.get("demonstration") if isinstance(entry.get("demonstration"), dict) else None
    views = [
        _violence(state, harm, names) if harm else None,
        None if harm else _theft(entry, names),  # A weapon grabbed for an attack is part of the attack.
        _demonstration(shown) if shown else None,
        None if shown or harm else _making(entry),
        _installing(entry.get("install")),
        _lifting(state, entry.get("lift_out")),
        _gift(entry.get("give")),
        _help(entry.get("treated")),
    ]
    return [view for view in views if view]


def _view(kind: str, victim: str | None, item: str | None, clear: tuple, vague: tuple, **extra) -> dict:
    """One thing onlookers can see: clearly (summary, short, severity) when close, vaguely from further off."""
    return {
        "kind": kind,
        "victim": victim,
        "item": item,
        **extra,
        "clear": dict(zip(("summary", "short", "severity"), clear)),
        "vague": dict(zip(("summary", "short", "severity"), vague)),
    }


SHOWN = {"think": False, "works": True, "audience": []}  # Seen and remembered, not reacted to.


def _violence(state: State, harm: dict, names: dict) -> dict:
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
    severity = {"killed": 3, "wounded": 2, "disabled": 3, "knocked_out": 3, "deflected": 1, "missed": 1}[harm["result"]]
    fell = harm["result"] in ("killed", "disabled", "knocked_out")
    return _view(
        "violence",
        harm["target_id"],
        None,
        (f"The stranger {verb} {victim}{'' if 'threw' in verb else how}. {outcome}", short, severity),
        (
            f"There was a scuffle near the stranger and {victim} went down."
            if fell
            else f"There was a scuffle near the stranger; {victim} cried out.",
            f"was in a fight with {victim}",
            max(1, severity - 1),
        ),
    )


def _theft(entry: dict, names: dict) -> dict | None:
    claims = [c for c in entry.get("property") or [] if c.get("how") != "used"]  # Using isn't taking (D-46).
    if not claims:
        return None
    claim = claims[0]
    owner = names.get(claim["owner_id"], "someone")
    verb = {
        "taken": "took",
        "used up": "used up",
        "used": "used",
        "given away": "gave away",
        "gathered from": "took some of",
    }.get(claim["how"], f"{claim['how']}")
    return _view(
        "theft",
        claim["owner_id"],
        claim["name"],
        (f"The stranger {verb} {owner}'s {claim['name']} without asking.", f"stole {owner}'s {claim['name']}", 2),
        (f"The stranger was handling {owner}'s things.", f"was handling {owner}'s things", 1),
    )


def _demonstration(shown: dict) -> dict:
    return _view(
        "demonstration",
        None,
        shown["object_name"],
        (shown["observed"], f"showed off a {shown['object_name']}", 1),
        ("The stranger was showing people something; it was hard to see what.", "was showing something", 0),
        audience=shown.get("audience_ids", []),
        think=False,
        works=shown["works"],
        wonder=shown.get("wonder", "ordinary"),
    )


def _making(entry: dict) -> dict | None:
    """Watching something being made is being shown it (D-54)."""
    if not entry.get("made_ids"):
        return None
    name = entry.get("made_name") or "something"
    return _view(
        "demonstration",
        None,
        name,
        (f"The stranger made a {name} in front of them: {entry.get('reason', '')}", f"made a {name}", 1),
        ("The stranger was making something; it was hard to see what.", "was making something", 0),
        **SHOWN,
        wonder="ordinary",
    )


def _aids(plan: dict) -> str:
    using = f" using the {' and the '.join(plan['aid_names'])}" if plan["aid_names"] else ""
    helpers = plan.get("helper_names") or []
    helping = f"{',' if using else ''} with {' and '.join(helpers)} helping" if helpers else ""
    return using + helping


def _installing(placed) -> dict | None:
    if not isinstance(placed, dict):
        return None
    return _view(
        "demonstration",
        None,
        placed["object_name"],
        (
            f"The stranger got the {placed['object_name']} up into the {placed['into_name']}{_aids(placed)}.",
            f"put the {placed['object_name']} in place",
            1,
        ),
        ("The stranger was heaving something heavy into place.", "was working on something heavy", 0),
        **SHOWN,
        clear_cells=tuning.SIGHT_CELLS,  # A beam going up: anyone can see it.
    )


def _lifting(state: State, lifted) -> dict | None:
    """Taking the bar off the city gate is an assault on it, unless it's work someone asked for (Tomas's swap)."""
    if not isinstance(lifted, dict):
        return None
    name = lifted["object_name"]
    if lifted["from_id"] == m2.GATE_FIXTURE and not gate_work_agreed(state):
        return _view(
            "breach",
            None,
            name,
            (
                f"The stranger lifted the {name} off the city gate{_aids(lifted)}: the gate is unbarred.",
                "unbarred the city gate",
                3,
            ),
            ("The stranger was doing something at the gate.", "was meddling at the gate", 2),
            clear_cells=tuning.SIGHT_CELLS,
        )
    return _view(
        "demonstration",
        None,
        name,
        (
            f"The stranger got the {name} out of the {lifted['from_name']}{_aids(lifted)}.",
            f"took the {name} down",
            1,
        ),
        ("The stranger was heaving something heavy down.", "was working on something heavy", 0),
        **SHOWN,
        clear_cells=tuning.SIGHT_CELLS,
    )


def _gift(give) -> dict | None:
    if not isinstance(give, dict):
        return None
    things, to = " and ".join(give["names"]), give["recipient_name"]
    return _view(
        "gift",
        give["recipient_id"],
        things,
        (f"The stranger gave {to} a {things}.", f"gave {to} a {things}", 1),
        (f"The stranger handed something to {to}.", f"handed something to {to}", 0),
        think=False,
    )


def _help(treated) -> dict | None:
    """Binding someone's wound, splinting a limb (D-49): help, seen and remembered."""
    if not isinstance(treated, dict):
        return None
    patient = treated["patient_name"]
    return _view(
        "help",
        treated["patient_id"],
        treated["remedy"],
        (
            f"The stranger treated {patient}'s {treated['what']} with a {treated['remedy']}.",
            f"treated {patient}'s wound",
            1,
        ),
        (f"The stranger was tending to {patient}.", f"tended to {patient}", 0),
        think=False,
    )


SOURCES = {"violence": "victim", "theft": "victim", "gift": "received", "help": "received"}


def gate_work_agreed(state: State) -> bool:
    """The stranger has an accepted deal to put a new bar on the gate (Tomas's swap): taking the old one out is
    that work, not an assault on the gate."""
    for deal in (state.get("agreements") or {}).values():
        if deal.get("status") != "accepted":
            continue
        if (cast.offer_of(state, deal).get("done_when") or {}).get("kind") == "installed":
            return True
    return False


def perceive(state: State, entry: dict) -> list[dict]:
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
            if cast.distance(npc, here) <= tuning.SIGHT_CELLS and paths.line_of_sight(state, cast.cell(npc), here):
                views.append(cast.distance(npc, here))
            if (
                victim is not None
                and cast.distance(npc, victim) <= tuning.SIGHT_CELLS
                and paths.line_of_sight(state, cast.cell(npc), cast.cell(victim))
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


def apply_perceptions(state: State, perceptions: list[dict]) -> None:
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


def _react_at_once(state: State, npc: Npc, memory: Memory, barked: bool) -> bool:
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
