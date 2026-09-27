"""Paint world sprites for the seed-4 road materials with the game's illustrator role.

Run once after adding OPENAI_API_KEY to backend/.env, then let Godot import the files:
    backend/.venv/Scripts/python.exe tools/generate_material_art.py [--force] [object_id ...]
Writes assets/generated/materials/<object_id>.png (committed art; Godot prefers it over placeholders).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import m2  # noqa: E402
from ai import config, illustrator  # noqa: E402

OUT = ROOT / "assets" / "generated" / "materials"


def main(argv: list[str]) -> int:
    force = "--force" in argv
    wanted = [a for a in argv if not a.startswith("--")] or list(m2.NEW_PUBLIC_MATERIALS)
    if config.mode() != "live":
        print(f"AI mode is '{config.mode()}'. Add OPENAI_API_KEY to backend/.env (and don't set AI_MODE=stub).")
        return 1
    failures = 0
    for object_id in wanted:
        name = m2.NEW_PUBLIC_MATERIALS[object_id][0]
        materials, description, _, _ = m2.MATERIAL_SEED[object_id]
        destination = OUT / f"{object_id}.png"
        if destination.exists() and not force:
            print(f"skip   {object_id}: already painted (use --force to repaint)")
            continue
        call = illustrator.generate_sprite({"name": name, "description": description, "materials": materials},
                                           destination)
        failures += call.status != "ready"
        print(f"{call.status:6} {object_id}: {call.model} {call.latency_ms} ms {call.error or ''}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
