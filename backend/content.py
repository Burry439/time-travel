"""Every authored content file, read once. Game code takes its content from here and never opens data files itself
(GDD section 8, D-58), so there is one place to see what the game is made of and one place to check it."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def read(relative: str) -> dict:
    return json.loads((DATA / relative).read_text(encoding="utf-8"))


GEOMETRY = read("world_geometry.json")  # The map: buildings, obstacles, the gate.
PLACES = read("places.json")["places"]  # Named places people talk about and go to.
ROUTINES = read("npc_routines.json")  # Each person's day: anchors and dwell times.
CARDS = read("content/npc_cards.json")["npcs"]  # Who each person is.
LINES = read("content/lines.json")  # Authored lines ("lines") and regard cues ("cues").
MATERIALS = read("content/materials.json")  # What things are made of, for the judge and the validator.
GEAR = read("content/gear.json")  # Weapons, armour, shields, remedies.
WORLD_OBJECTS = read("content/world_objects.json")  # The things lying about the world at the start.
TUTORIAL = read("content/tutorial.json")  # The tutorial's steps.
