"""Saved NPC activity plans and deterministic execution.

Routine selection is deliberately separate from route execution. A plan the decider chose (village.py,
source "agenda") walks the same way; when its dwell is over the person drifts back to their routine
until they next decide (GDD D-37).
"""

from __future__ import annotations

from copy import deepcopy

import content
import effects
import paths
from shapes import Npc, State


def anchors(state: State, npc_id: str) -> list[list]:
    """A person's round in this level's cast (data/content/levels): each anchor is (cell x, cell y, activity at
    arrival, dwell milliseconds); [] for someone not in the cast."""
    return (content.level(state)["cast"].get(npc_id) or {}).get("anchors") or []


def seed_npcs(state: State) -> list[Npc]:
    """Everyone in the level at the start (its cast, in order): who they are from their card, the short title shown
    over them (role), their pace (step_ms) and goal, at their round's first place."""
    blocked = paths.standing_grid(state)
    seeded = []
    for index, (npc_id, spec) in enumerate(content.level(state)["cast"].items()):
        goal, stops = spec["goal"], spec["anchors"]
        assert all((x, y) not in blocked for x, y, _, _ in stops)
        npc = {
            "id": npc_id,
            "name": content.CARDS[npc_id]["name"],
            "role": spec["role"],
            "x": stops[0][0],
            "y": stops[0][1],
        }
        npc["controller"] = {
            "source": "routine",
            "goal": goal,
            "activity": stops[0][2],
            "anchor_index": 0,
            "destination": [npc["x"], npc["y"]],
            "path": [],
            "step_carry_ms": 0,
            "step_ms": spec["step_ms"],
            "next_at_ms": stops[0][3] + index * 170,
        }
        if spec.get("conditions"):  # What ails them from the start (Kade's knees, D-61).
            npc["conditions"] = [
                {"kind": c["kind"], "area": c.get("area", "torso"), "since": 0, "treated": 0}
                for c in spec["conditions"]
            ]
        seeded.append(npc)
    return seeded


def _route(start: tuple[int, int], goal: tuple[int, int], blocked: paths.Grid) -> list[list[int]]:
    """The walk to the next place on their round; none if something put across the way shuts it off (D-65): they
    stay where they are until it's cleared."""
    try:
        return paths.route(start, goal, blocked)
    except ValueError:
        return []


def choose_routine_plan(state: State, npc: Npc, blocked: paths.Grid) -> None:
    """Current planner. The decider can replace this choice with another valid plan."""
    controller = npc["controller"]
    round_ = anchors(state, npc["id"])
    next_index = (controller["anchor_index"] + 1) % len(round_)
    x, y, _, _ = round_[next_index]
    controller["anchor_index"] = next_index
    controller["destination"] = [x, y]
    controller["path"] = _route((npc["x"], npc["y"]), (x, y), blocked)
    controller["activity"] = "walk"
    controller["step_carry_ms"] = 0


def advance_npcs(state: State, npcs: list[Npc], elapsed_ms: int, now_ms: int) -> list[dict]:
    updated = deepcopy(npcs)
    blocked = paths.standing_grid(state)
    arrival_time = now_ms + elapsed_ms
    for npc in updated:
        controller = npc.get("controller")
        if controller is None or not npc.get("alive", True) or controller.get("source") == "job":
            continue  # Dead, or busy with something they decided to do (minds.advance_world moves them).
        if controller["activity"] != "walk":
            if arrival_time >= controller["next_at_ms"] and controller["source"] in ("routine", "agenda"):
                controller["source"] = "routine"  # A chosen plan is done: back to the usual round.
                choose_routine_plan(state, npc, blocked)
            continue
        controller["step_carry_ms"] += elapsed_ms
        while controller["step_carry_ms"] >= controller["step_ms"] and controller["path"]:
            if tuple(controller["path"][0]) in blocked:  # Something was put across the way (D-65): go around.
                goal = controller["path"][-1]
                around = _route((npc["x"], npc["y"]), tuple(goal), blocked)
                controller["path"] = around
                if not around:
                    break
            controller["step_carry_ms"] -= controller["step_ms"]
            npc["x"], npc["y"] = controller["path"].pop(0)
            if effects.spring(state, npc, (npc["x"], npc["y"]), arrival_time):  # A hidden trap (D-65): caught.
                controller["path"] = []
                break
        if not controller["path"]:
            if controller["source"] == "agenda":
                activity, dwell_ms = controller.get("arrive_activity", "look"), controller.get("dwell_ms", 30_000)
            else:
                _, _, activity, dwell_ms = anchors(state, npc["id"])[controller["anchor_index"]]
            controller["activity"] = activity
            controller["next_at_ms"] = arrival_time + dwell_ms
            controller["step_carry_ms"] = 0
    return updated
