"""Saved NPC activity plans and deterministic execution.

Routine selection is deliberately separate from route execution. A later Jev
decision may supply a validated destination/activity without changing movement.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
from pathlib import Path


# Each anchor is (cell x, cell y, activity at arrival, dwell milliseconds).
# This file also drives the editor's visible activity-anchor overlay.
_SOURCE = json.loads((Path(__file__).resolve().parents[1] / "data" / "npc_routines.json").read_text())
ROUTINES = {npc_id: (spec["goal"], spec["anchors"]) for npc_id, spec in _SOURCE.items()}


def blocked_cells(geometry: dict) -> set[tuple[int, int]]:
    return {
        (cx, cy)
        for item in geometry["buildings"] + geometry["obstacles"]
        for x, y, width, height in [item["cells"]]
        for cx in range(x, x + width)
        for cy in range(y, y + height)
    }


def route(start: tuple[int, int], goal: tuple[int, int], blocked: set[tuple[int, int]]) -> list[list[int]]:
    if start == goal:
        return []
    frontier = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while frontier:
        x, y = frontier.popleft()
        for cell in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if cell in previous or cell in blocked or not (0 <= cell[0] < 96 and 9 <= cell[1] < 72):
                continue
            previous[cell] = (x, y)
            if cell == goal:
                path: list[list[int]] = []
                cursor = goal
                while cursor != start:
                    path.append([cursor[0], cursor[1]])
                    cursor = previous[cursor]  # type: ignore[assignment]
                return list(reversed(path))
            frontier.append(cell)
    raise ValueError(f"No safe NPC route from {start} to {goal}")


def seed_npcs(npcs: list[dict], geometry: dict) -> list[dict]:
    seeded = deepcopy(npcs)
    blocked = blocked_cells(geometry)
    for index, npc in enumerate(seeded):
        goal, anchors = ROUTINES[npc["id"]]
        assert (npc["x"], npc["y"]) == tuple(anchors[0][:2])
        assert all((x, y) not in blocked for x, y, _, _ in anchors)
        npc["controller"] = {
            "source": "routine", "goal": goal, "activity": anchors[0][2],
            "anchor_index": 0, "destination": [npc["x"], npc["y"]],
            "path": [], "step_carry_ms": 0,
            "step_ms": 360 if "guard" in npc["role"].lower() or npc["id"] in ("npc_elin_west", "npc_kade_east") else 440,
            "next_at_ms": anchors[0][3] + index * 170,
        }
    return seeded


def choose_routine_plan(npc: dict, blocked: set[tuple[int, int]]) -> None:
    """Current planner. Jev can later replace this choice with another valid plan."""
    controller = npc["controller"]
    _, anchors = ROUTINES[npc["id"]]
    next_index = (controller["anchor_index"] + 1) % len(anchors)
    x, y, _, _ = anchors[next_index]
    controller["anchor_index"] = next_index
    controller["destination"] = [x, y]
    controller["path"] = route((npc["x"], npc["y"]), (x, y), blocked)
    controller["activity"] = "walk"
    controller["step_carry_ms"] = 0


def advance_npcs(npcs: list[dict], elapsed_ms: int, now_ms: int, geometry: dict) -> list[dict]:
    updated = deepcopy(npcs)
    blocked = blocked_cells(geometry)
    arrival_time = now_ms + elapsed_ms
    for npc in updated:
        controller = npc.get("controller")
        if controller is None or not npc.get("alive", True) or controller.get("source") == "job":
            continue  # Dead, or busy with something they decided to do (minds.advance_world moves them).
        if controller["activity"] != "walk":
            if arrival_time >= controller["next_at_ms"] and controller["source"] == "routine":
                choose_routine_plan(npc, blocked)
            continue
        controller["step_carry_ms"] += elapsed_ms
        while controller["step_carry_ms"] >= controller["step_ms"] and controller["path"]:
            controller["step_carry_ms"] -= controller["step_ms"]
            npc["x"], npc["y"] = controller["path"].pop(0)
        if not controller["path"]:
            _, anchors = ROUTINES[npc["id"]]
            _, _, activity, dwell_ms = anchors[controller["anchor_index"]]
            controller["activity"] = activity
            controller["next_at_ms"] = arrival_time + dwell_ms
            controller["step_carry_ms"] = 0
    return updated
