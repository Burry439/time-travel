"""Saved NPC activity plans and deterministic execution.

Routine selection is deliberately separate from route execution. A plan the decider chose (village.py,
source "agenda") walks the same way; when its dwell is over the person drifts back to their routine
until they next decide (GDD D-37).
"""

from __future__ import annotations

from copy import deepcopy

import content
import paths
from shapes import Npc

# Each person: role (the short title shown over them), step_ms (their walking pace), goal and anchors, each anchor
# (cell x, cell y, activity at arrival, dwell milliseconds). The file also drives the editor's anchor overlay.
ROUTINES = {npc_id: (spec["goal"], spec["anchors"]) for npc_id, spec in content.ROUTINES.items()}


def seed_npcs() -> list[Npc]:
    """Everyone in the world at the start (data/npc_routines.json, in its order): who they are from their card,
    the short title shown over them, at their day's first place."""
    blocked = paths.obstacle_cells()
    seeded = []
    for index, (npc_id, spec) in enumerate(content.ROUTINES.items()):
        goal, anchors = ROUTINES[npc_id]
        assert all((x, y) not in blocked for x, y, _, _ in anchors)
        npc = {
            "id": npc_id,
            "name": content.CARDS[npc_id]["name"],
            "role": spec["role"],
            "x": anchors[0][0],
            "y": anchors[0][1],
        }
        npc["controller"] = {
            "source": "routine",
            "goal": goal,
            "activity": anchors[0][2],
            "anchor_index": 0,
            "destination": [npc["x"], npc["y"]],
            "path": [],
            "step_carry_ms": 0,
            "step_ms": spec["step_ms"],
            "next_at_ms": anchors[0][3] + index * 170,
        }
        seeded.append(npc)
    return seeded


def choose_routine_plan(npc: Npc, blocked: set[tuple[int, int]]) -> None:
    """Current planner. The decider can replace this choice with another valid plan."""
    controller = npc["controller"]
    _, anchors = ROUTINES[npc["id"]]
    next_index = (controller["anchor_index"] + 1) % len(anchors)
    x, y, _, _ = anchors[next_index]
    controller["anchor_index"] = next_index
    controller["destination"] = [x, y]
    controller["path"] = paths.route((npc["x"], npc["y"]), (x, y), blocked)
    controller["activity"] = "walk"
    controller["step_carry_ms"] = 0


def advance_npcs(npcs: list[Npc], elapsed_ms: int, now_ms: int) -> list[dict]:
    updated = deepcopy(npcs)
    blocked = paths.obstacle_cells()
    arrival_time = now_ms + elapsed_ms
    for npc in updated:
        controller = npc.get("controller")
        if controller is None or not npc.get("alive", True) or controller.get("source") == "job":
            continue  # Dead, or busy with something they decided to do (minds.advance_world moves them).
        if controller["activity"] != "walk":
            if arrival_time >= controller["next_at_ms"] and controller["source"] in ("routine", "agenda"):
                controller["source"] = "routine"  # A chosen plan is done: back to the usual round.
                choose_routine_plan(npc, blocked)
            continue
        controller["step_carry_ms"] += elapsed_ms
        while controller["step_carry_ms"] >= controller["step_ms"] and controller["path"]:
            controller["step_carry_ms"] -= controller["step_ms"]
            npc["x"], npc["y"] = controller["path"].pop(0)
        if not controller["path"]:
            if controller["source"] == "agenda":
                activity, dwell_ms = controller.get("arrive_activity", "look"), controller.get("dwell_ms", 30_000)
            else:
                _, anchors = ROUTINES[npc["id"]]
                _, _, activity, dwell_ms = anchors[controller["anchor_index"]]
            controller["activity"] = activity
            controller["next_at_ms"] = arrival_time + dwell_ms
            controller["step_carry_ms"] = 0
    return updated
