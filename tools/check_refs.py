"""Every reference to the game from another script resolves (tools/check.ps1, D-58).

Scripts reach the game node (scripts/main.gd) as `game.X` (UI) or `scene.X` (smokes and tools); its parts as
`game.net.X`, `game.view.X` and so on. Godot doesn't check those names when it compiles (game is a plain Node2D), so
a renamed or moved member would only fail when that line runs. This checks each one against the members of
main.gd and of the part's own script.
    python tools/check_refs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "scripts" / "main.gd"
MEMBER = re.compile(
    r"^(?:@onready\s+|@export\s+)?(?:static\s+)?(?:func|var|const|signal)\s+([A-Za-z_]\w*)", re.MULTILINE
)
# Node2D / Node methods and properties other scripts use on the game node or its parts.
NODE_API = {
    "add_child",
    "remove_child",
    "get_node",
    "get_node_or_null",
    "has_node",
    "get_viewport",
    "get_viewport_rect",
    "get_tree",
    "create_tween",
    "get_global_mouse_position",
    "get_world_2d",
    "position",
    "global_position",
    "name",
    "visible",
    "get_children",
    "find_children",
    "is_inside_tree",
    "queue_free",
    "get_parent",
    "call_deferred",
    "set_meta",
    "get_meta",
    "has_meta",
    "modulate",
    "z_index",
    "to_local",
    "to_global",
    "show",
    "hide",
}


def members(path: Path) -> set[str]:
    return set(MEMBER.findall(path.read_text(encoding="utf-8")))


def check() -> list[str]:
    main = MAIN.read_text(encoding="utf-8")
    main_members = members(MAIN)
    parts = {}  # attr -> its script's members, for every `x = preload(...).new()` or `x = Const.new()`.
    consts = dict(re.findall(r'^const (\w+) := preload\("res://([^"]+)"\)', main, re.MULTILINE))
    for attr, source in re.findall(r"^\s*(\w+) = (\w+|preload\(\"res://[^\"]+\"\))\.new\(\)", main, re.MULTILINE):
        inline = re.search(r'res://([^"]+)', source)
        script = consts.get(source) or (inline.group(1) if inline else None)
        if script:
            parts[attr] = members(ROOT / script)
    problems = []
    for path in sorted((ROOT / "scripts").rglob("*.gd")) + sorted((ROOT / "tools").rglob("*.gd")):
        if path == MAIN:
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\b(game|scene)\.([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?", text):
            first, second = m.group(2), m.group(3)
            line = text.count("\n", 0, m.start()) + 1
            where = f"{path.relative_to(ROOT)}:{line}: {m.group(0)}"
            if first in parts:
                if second and second not in parts[first] and second not in NODE_API:
                    problems.append(f"{where}: {first} has no {second}")
            elif first not in main_members and first not in NODE_API:
                problems.append(f"{where}: the game has no {first}")
    return problems


if __name__ == "__main__":
    found = check()
    for problem in found:
        print(problem)
    print("CHECK REFS " + ("FAILED" if found else "PASSED"))
    sys.exit(1 if found else 0)
