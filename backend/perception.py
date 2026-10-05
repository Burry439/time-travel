"""Physical perception: record each step for people who can actually see or hear it.
Evidence queues personal reactions; the person's model chooses their interpretation and response."""

from __future__ import annotations

import cast
import effects
import evidence
import m2
import paths
import reputation
import tuning
from shapes import State


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
        *[_theft({**entry, "property": [claim]}, names) for claim in entry.get("property", [])],
        _demonstration(shown) if shown else None,
        None if shown or harm else _making(entry),
        _installing(entry.get("install")),
        _lifting(state, entry.get("lift_out")),
        _gift(entry.get("give")),
        _help(entry.get("treated")),
    ]
    views = [view for view in views if view]
    if not views and (entry.get("seen_as") or "").strip():  # Any other deed is still seen (D-65): a kiss, a soaking.
        views.append(_deed(entry))
    return views + [_signal(s) for s in entry.get("signals") or []]


def _signal(signal: dict) -> dict:
    """A sound or a sign (D-65): heard through walls within its reach, or seen far off in a line of sight. Whoever
    can see the stranger knows who made it; everyone else only that it came from somewhere."""
    heard = signal["kind"] == "sound"
    text = signal["text"].rstrip(".")
    return _view(
        "signal",
        None,
        None,
        (f"The stranger made a signal: {text}.", f"{'heard' if heard else 'saw'} the stranger: {text}"[:80], 1),
        (f"You {'heard' if heard else 'saw'}: {text}.", f"{'heard' if heard else 'saw'} {text}"[:80], 1),
        reach=signal["cells"],
        sight=signal["sight"],
        think=True,
    )


def _compass(frm, to) -> str:
    """Which way something is, in words, from where someone stands (north is up the map)."""
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    if abs(dx) < 1 and abs(dy) < 1:
        return "right here"
    ns = "north" if dy < -abs(dx) / 2 else "south" if dy > abs(dx) / 2 else ""
    ew = "west" if dx < -abs(dy) / 2 else "east" if dx > abs(dy) / 2 else ""
    return f"the {ns}{ew}"


def _deed(entry: dict) -> dict:
    """A deed no specific view covers, as an onlooker saw it (the judge's seen_as). The person it touched remembers
    it as done to them and thinks about it in their own call; everyone else in sight remembers it."""
    touched = [i for i in entry.get("touched", []) if i != "player"]
    seen = " ".join(entry["seen_as"].split())[:300]
    return _view(
        "deed",
        touched[0] if touched else None,
        None,
        (seen, seen[:80], 1 if touched else 0),
        ("The stranger was doing something; it was hard to see what.", "was doing something", 0),
        think=bool(touched),
        audience=touched[1:],
    )


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


SHOWN = {"think": True, "works": True, "audience": []}  # Seen and remembered, not reacted to.


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
        object_id=claim["id"],
    )


def _demonstration(shown: dict) -> dict:
    return _view(
        "demonstration",
        None,
        shown["object_name"],
        (shown["observed"], f"showed off a {shown['object_name']}", 1),
        ("The stranger was showing people something; it was hard to see what.", "was showing something", 0),
        audience=shown.get("audience_ids", []),
        think=True,
        works=shown["works"],
        wonder=shown.get("wonder", "ordinary"),
        object_id=shown["object_id"],
        application=tuple(
            sorted(shown.get("used_ids", []))
        ),  # What was shown, for stories that ask what it was (D-61).
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
        **{**SHOWN, "works": False},
        application="construction",
        wonder="ordinary",
        object_id=entry["made_ids"][0],
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
        object_id=placed["object_id"],  # Which thing went up: stories ask who saw it (D-63).
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
        think=True,
        object_id=give["item_ids"][0],
        object_ids=list(give["item_ids"]),  # Which things changed hands: stories ask who saw the gift (D-63).
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
        think=True,
    )


SOURCES = {"violence": "victim", "theft": "victim", "gift": "received", "help": "received", "deed": "victim"}


def gate_work_agreed(state: State) -> bool:
    """The stranger has an accepted deal to put a new bar on the gate (Tomas's swap): taking the old one out is
    that work, not an assault on the gate."""
    for deal in (state.get("agreements") or {}).values():
        if deal.get("status") != "accepted":
            continue
        if (cast.offer_of(state, deal).get("done_when") or {}).get("kind") == "installed":
            return True
    return False


def perceive(state: State, entry: dict, before: State | None = None) -> list[dict]:
    """Memories for everyone who could see what the player just did (and for the people it involved).

    Close witnesses see what happened; those further off only see something going on.
    """
    here = tuple(entry.get("player_cell", cast.player_cell(state)))
    perceptions = []
    for seen in _describe(state, entry):
        victim = cast.find(state["npcs"], seen["victim"] or "")
        involved = {seen["victim"]} - {None}
        for npc in state["npcs"]:
            observer = cast.find(before["npcs"], npc["id"]) if before else npc
            if observer is None or not observer.get("alive", True) or observer.get("down"):
                continue  # Awareness is measured immediately before impact.
            npc = observer
            views = []
            blind = effects.limited(npc, "see")  # Asleep or blindfolded: they see nothing (D-65).
            if seen["kind"] == "signal":
                memory = _signalled(state, entry, seen, npc, here, blind)
                if memory:
                    perceptions.append({"npc_id": npc["id"], "memory": memory, "think": True})
                continue
            if blind and npc["id"] not in involved:
                continue
            if (
                not blind
                and cast.distance(npc, here) <= tuning.SIGHT_CELLS
                and paths.line_of_sight(state, cast.cell(npc), here)
            ):
                views.append(cast.distance(npc, here))
            if (
                victim is not None
                and not blind
                and cast.distance(npc, victim) <= tuning.SIGHT_CELLS
                and paths.line_of_sight(state, cast.cell(npc), cast.cell(victim))
            ):
                views.append(cast.distance(npc, victim))
            close = npc["id"] in involved
            if not (close or views):
                continue
            clarity = "clear" if close or min(views) <= seen.get("clear_cells", tuning.CLEAR_VIEW_CELLS) else "vague"
            source = (
                SOURCES.get(seen["kind"], "shown")
                if npc["id"] == seen["victim"]
                else "shown"
                if npc["id"] in seen.get("audience", []) and views
                else "witnessed"
            )
            memory = {
                "kind": seen["kind"],
                "actor_id": entry.get("actor_id", "player"),
                "victim": seen["victim"],
                "item": seen.get("item"),
                **seen[clarity],
                "clarity": clarity,
                "at": entry.get("sim_time_ms", state["sim_time_ms"]),
                "event": entry.get("event_id"),
                "step_number": entry.get("step_number", 1),
                "source": source,
            }
            if entry.get("actor_id", "player") != "player":
                doer = cast.find(state["npcs"], entry["actor_id"])
                memory["summary"] = memory["summary"].replace("The stranger", doer["name"])
                memory["short"] = memory["short"].replace("stranger", doer["name"])
            else:
                _unmasked(memory, (before or state)["player"], npc)
            if "works" in seen:
                memory["works"] = seen["works"]
            if seen.get("wonder") and clarity == "clear":
                memory["wonder"] = seen["wonder"]
            if seen.get("object_id") and clarity == "clear":
                memory["object_id"] = seen["object_id"]
                memory["revision"] = state["objects"].get(seen["object_id"], {}).get("revision", 0)
                memory["application"] = seen.get("application", "function")
            if seen.get("object_ids") and clarity == "clear":
                memory["object_ids"] = list(seen["object_ids"])
            if npc["id"] == seen["victim"]:  # They tell it in the first person: "attacked me", "stole my plank".
                memory["short"] = memory["short"].replace(f"{npc['name']}'s", "my").replace(npc["name"], "me")
            perceptions.append({"npc_id": npc["id"], "memory": memory, "think": seen.get("think", True)})
    evidence.record(state, entry, perceptions)
    return perceptions


def _unmasked(memory: dict, stranger: dict, npc: dict) -> None:
    """A disguised stranger (D-65): whoever doesn't see through it remembers someone else doing it, so it isn't held
    against the stranger as they know them."""
    mask = effects.disguise_of(stranger)
    if mask and not effects.recognises(npc, stranger):
        memory["summary"] = memory["summary"].replace("The stranger", f"Someone {mask}")
        memory["short"] = memory["short"].replace("the stranger", f"someone {mask}")
        memory["actor_id"] = effects.DISGUISED


def _signalled(state: State, entry: dict, seen: dict, npc: dict, here: tuple, blind) -> dict | None:
    """What one person makes of a sound or a sign: heard within its reach (walls don't stop it, and the blindfolded
    hear too), or seen within its reach in a line of sight. Seeing the stranger at it, they know who; otherwise
    only which way it came from."""
    far = cast.distance(npc, here)
    in_sight = not blind and paths.line_of_sight(state, cast.cell(npc), here)
    if far > seen["reach"] or (seen["sight"] and not in_sight):
        return None
    knows = in_sight and far <= tuning.SIGHT_CELLS
    view = dict(seen["clear" if knows else "vague"])
    if not knows:
        view["summary"] = view["summary"].rstrip(".") + f", from {_compass(cast.cell(npc), here)}."
    memory = {
        "kind": "signal",
        "actor_id": entry.get("actor_id", "player") if knows else None,
        "victim": None,
        "item": None,
        **view,
        "clarity": "clear" if knows else "vague",
        "at": entry.get("sim_time_ms", state["sim_time_ms"]),
        "event": entry.get("event_id"),
        "step_number": entry.get("step_number", 1),
        "source": "witnessed",
    }
    if knows and entry.get("actor_id", "player") == "player":
        _unmasked(memory, state["player"], npc)
    return memory


def apply_perceptions(state: State, perceptions: list[dict]) -> None:
    """Remember what was seen; people who clearly saw a crime react at once by code (they turn, they're angry
    or afraid, the nearest one shouts), and then decide what to do about it (the decider)."""
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
        if npc is None:
            continue
        memory = perception["memory"]
        reputation.remember(npc, memory)
        if perception.get("think", True):
            cast.mind(npc)["rethinks"] = 0
            cast.add_pending(state, npc["id"], "decide", memory["source"])
        if memory["kind"] in reputation.CRIME_KINDS and memory.get("clarity") == "clear":
            cast.mind(npc)["facing_player"] = True
    # A previously chosen defensive plan can start instantly. New motives wait for that person's judgment.
    import combat

    fighters = [
        p["npc_id"]
        for p in perceptions
        if p["memory"]["kind"] == "violence"
        and p["memory"].get("actor_id", "player") in ("player", effects.DISGUISED)
        and (cast.mind(cast.find(state["npcs"], p["npc_id"])).get("standing_plan") or {}).get("defend")
        and not cast.find(state["npcs"], p["npc_id"]).get("down")
        and cast.find(state["npcs"], p["npc_id"]).get("alive", True)
    ]
    if fighters and state["player"].get("alive", True):
        combat.start(state, fighters, state["sim_time_ms"], "violence")
