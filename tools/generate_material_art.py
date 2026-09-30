"""Paint world sprites for the seed-4 road materials with the game's illustrator role.

Run once after adding OPENAI_API_KEY to backend/.env, then let Godot import the files:
    backend/.venv/Scripts/python.exe tools/generate_material_art.py [--force] [object_id ...]
Writes assets/generated/materials/<object_id>.png (committed art; Godot prefers it over placeholders).
Then trim and shrink the new pictures to the size the game shows (D-52), and import:
    Godot --headless --path . --script res://tools/shrink_material_art.gd
    Godot --headless --path . --import
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import m2  # noqa: E402
import tutorial  # noqa: E402
from ai import config, illustrator  # noqa: E402

OUT = ROOT / "assets" / "generated" / "materials"


def paintable() -> dict[str, dict]:
    """Every seeded public object without scene art: seed-4 road items and data/content/world_objects.json."""
    records = {}
    for object_id, (name, *_rest) in m2.NEW_PUBLIC_MATERIALS.items():
        materials, description, _, _ = m2.MATERIAL_SEED[object_id]
        records[object_id] = {"name": name, "description": description, "materials": materials}
    for spec in m2.WORLD_CONTENT["objects"]:
        if spec.get("no_sprite"):
            continue  # Drawn by something else (a building's art, the stranger's own painting).
        records[spec["id"]] = {key: spec[key] for key in ("name", "description", "materials")}
    for oid, name, _mass, _length, materials, description, *_rest in tutorial.PRACTICE_GEAR + tutorial.TUTORIAL_THINGS:
        records[oid] = {"name": name, "description": description, "materials": materials}
    return records


def main(argv: list[str]) -> int:
    force = "--force" in argv
    records = paintable()
    wanted = [a for a in argv if not a.startswith("--")] or list(records)
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}'. Add OPENAI_API_KEY to backend/.env (and don't set AI_MODE=stub).")
        return 1
    failures = 0
    for object_id in wanted:
        destination = OUT / f"{object_id}.png"
        if destination.exists() and not force:
            print(f"skip   {object_id}: already painted (use --force to repaint)")
            continue
        call = illustrator.generate_sprite(records[object_id], destination)
        failures += call.status != "ready"
        print(f"{call.status:6} {object_id}: {call.model} {call.latency_ms} ms {call.error or ''}")
    print("Now run tools/shrink_material_art.gd and import (see the top of this file).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
