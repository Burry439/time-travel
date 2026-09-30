"""What people say out loud from the authored line bank: choosing lines in a voice that suits them, filling
in who and what, and saying it where the stranger may hear (the journal records what they do)."""

from __future__ import annotations

import cast
import content
import reputation
import tuning

LINES: dict[str, dict] = content.LINES["lines"]


FAMILY_WORDS = ("sister", "brother", "nephew", "aunt")


def say(
    npc: dict,
    text: str,
    now: int,
    state: dict,
    journal: list[dict],
    line_id: str | None = None,
    category: str = "heard",
) -> None:
    cast.mind(npc)["said"] = {"text": text, "at": now, "key": f"{npc['id']}:{now}:{len(journal)}"}
    if line_id:
        cast.mind(npc)["last_line"] = line_id
    if cast.distance(npc, state["player"]) <= tuning.HEAR_SHOUT_CELLS:
        journal.append({"kind": "npc", "npc_id": npc["id"], "category": category, "reason": f"{npc['name']}: “{text}”"})


def _family_word(text: str | None) -> str | None:
    """'her nephew Jory' -> 'my nephew'."""
    return next((f"my {word}" for word in FAMILY_WORDS if text and word in text), None)


def choose_lines(state: dict, npc: dict, action: str, slots: dict) -> list[tuple[str, str]]:
    """Up to two (line_id, text) choices for this action in voices that suit this person."""
    bank = LINES.get(action, {})
    tones = list(cast.card(npc).get("tones") or ["frightened"])
    worst = reputation.worst_memory(npc)
    if action == "shout_for_help" and worst and worst["kind"] == "theft":
        tones = ["theft"] + tones
    if worst and cast.is_family(npc, worst.get("victim")):
        tones = ["protective"] + tones
    if not cast.card(npc).get("guard"):
        tones = [t for t in tones if t != "official"]
    available = [t for t in dict.fromkeys(tones) if t in bank] or list(bank)[:1]
    choices = []
    for tone in available:
        for index, template in enumerate(bank[tone]):
            line_id = f"{action}.{tone}.{index}"
            if line_id == cast.mind(npc).get("last_line"):
                continue  # Never the same line twice in a row.
            try:
                choices.append((line_id, template.format(**slots)))
            except KeyError:
                continue
            break  # One line per tone, so the two choices differ in voice.
        if len(choices) == 2:
            break
    return choices


def slots(state: dict, npc: dict) -> dict:
    """Words the line bank fills in for this person: who was hurt, what was taken, their weapon.
    When they are the victim themselves the words are first person ("me", "mine")."""
    worst = reputation.worst_memory(npc)
    victim = cast.find(state["npcs"], (worst or {}).get("victim") or "")
    me = victim is not None and victim["id"] == npc["id"]
    family = _family_word(cast.relation(npc, victim["id"])) if victim and not me else None
    name = "me" if me else victim["name"] if victim else "someone"
    return {
        "victim": name,
        "relation": family or name,
        "short": (worst or {}).get("short", "caused trouble"),
        "item": (worst or {}).get("item") or "things",
        "owner": name,
        "owners": "mine" if me else f"{victim['name']}'s" if victim else "someone's",
        "weapon": cast.armed_with(state, npc) or "fists",
        "guard": "friend",
    }
