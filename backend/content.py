"""Every authored content file, read once. Game code takes its content from here and never opens data files itself
(GDD section 8, D-58), so there is one place to see what the game is made of and one place to check it.

A journey plays a level (data/content/levels, D-59): a scenario on a map (data/maps), with its people and things.
The village is the main game; the training levels each have their own small map and people."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INHERITED = ("map", "start", "objective", "cast")  # What a level takes from its base (things are added to).


def read(relative: str) -> dict:
    return json.loads((DATA / relative).read_text(encoding="utf-8"))


def _each(folder: str) -> dict[str, dict]:
    return {path.stem: read(f"{folder}/{path.name}") for path in sorted((DATA / folder).glob("*.json"))}


def _people() -> dict[str, dict]:
    """The village's cards, then each level's own people (data/content/people): one register, ids unique."""
    cards = dict(read("content/npc_cards.json")["npcs"])
    for name, extra in _each("content/people").items():
        clash = set(cards) & set(extra["npcs"])
        assert not clash, f"content/people/{name}.json repeats {sorted(clash)}"
        cards.update(extra["npcs"])
    return cards


def _things(entries: list) -> list[dict]:
    """A level's things: each a thing, or the name of a content file whose objects all lie about."""
    return [
        spec
        for entry in entries
        for spec in (read(f"content/{entry}.json")["objects"] if isinstance(entry, str) else [entry])
    ]


def _levels() -> dict[str, dict]:
    raw = _each("content/levels")

    def resolved(level_id: str) -> dict:
        level = raw[level_id]
        if not level.get("base"):
            return {**level, "things": _things(level.get("things", []))}
        parent = resolved(level["base"])
        inherited = {key: parent[key] for key in INHERITED if key in parent}
        return {**inherited, **level, "things": parent["things"] + _things(level.get("things", []))}

    return {level_id: resolved(level_id) for level_id in raw}


MAPS = _each("maps")  # Each map: its size, buildings, obstacles and named places.
LEVELS = _levels()  # Each level: its map, people, things and (if guided) steps.
CARDS = _people()  # Who each person is.
LINES = read("content/lines.json")  # Authored lines ("lines") and regard cues ("cues").
MATERIALS = read("content/materials.json")  # What things are made of, for the judge and the validator.
GEAR = read("content/gear.json")  # Weapons, armour, shields, remedies.


def level(state: dict) -> dict:
    """The level this journey plays (older journeys without one are the village)."""
    return LEVELS[state.get("scenario") or "village"]


def map_of(state: dict) -> dict:
    return MAPS[level(state)["map"]]
