"""The walkable map: which cells are blocked, how to get from one cell to another, and what can be seen from
where. The stranger, people on their routines and people on their jobs all walk the same grid (GDD section 8)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable

import content
import tuning

WIDTH, TOP, BOTTOM = 96, 9, 72  # The ground outside the wall: x from 0 to 95, y from 9 (the wall's foot) to 71.


def _cells(rectangles: Iterable[dict]) -> set[tuple[int, int]]:
    return {
        (cx, cy)
        for item in rectangles
        for bx, by, w, h in [item["cells"]]
        for cx in range(bx, bx + w)
        for cy in range(by, by + h)
    }


WALLS = _cells(content.GEOMETRY["buildings"])  # Buildings block sight; trees do not.


def obstacle_cells(cleared: set[str] | frozenset[str] = frozenset()) -> set[tuple[int, int]]:
    """Buildings, and obstacles (trees, rocks) not yet cleared away: nobody walks through them."""
    standing = content.GEOMETRY["buildings"] + content.GEOMETRY["obstacles"]
    return _cells(item for item in standing if item["name"] not in cleared)


def cleared_obstacles(state: dict) -> set[str]:
    """Geometry obstacles removed by play, such as felled trees."""
    return {
        o["geometry_name"] for o in state["objects"].values() if o.get("geometry_name") and o["condition"] != "usable"
    }


def blocked_cells(state: dict) -> set[tuple[int, int]]:
    return obstacle_cells(cleared_obstacles(state))


def walkable(cell: tuple[int, int], blocked: set) -> bool:
    return 0 <= cell[0] < WIDTH and TOP <= cell[1] < BOTTOM and cell not in blocked


def bfs(start: tuple[int, int], blocked: set, limit: int) -> tuple[dict, dict]:
    """Every cell reachable within limit steps: (the cell each was reached from, steps to it)."""
    previous, steps = {start: None}, {start: 0}
    frontier = deque([start])
    while frontier:
        cell = frontier.popleft()
        if steps[cell] >= limit:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt not in previous and walkable(nxt, blocked):
                previous[nxt], steps[nxt] = cell, steps[cell] + 1
                frontier.append(nxt)
    return previous, steps


def route(start: tuple[int, int], goal: tuple[int, int], blocked: set[tuple[int, int]]) -> list[list[int]]:
    """The whole walk from start to goal (a routine's next leg); it must exist."""
    if start == goal:
        return []
    frontier = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while frontier:
        x, y = frontier.popleft()
        for cell in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if cell in previous or not walkable(cell, blocked):
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


def next_step(start: tuple[int, int], goal: tuple[int, int], stop: float, blocked: set) -> tuple[int, int] | None:
    """One step toward being within stop of goal (someone on a job, a step per beat); None if there's no way."""
    previous, steps = bfs(start, blocked, 60)
    goals = [c for c in steps if math.dist(c, goal) <= stop]
    if not goals:
        return None
    cell = min(goals, key=lambda c: (steps[c], math.dist(c, goal)))
    while previous.get(cell) not in (start, None):
        cell = previous[cell]
    return None if cell == start else cell


def path_to_reach(
    start: tuple[int, int], target: tuple[int, int], blocked: set, limit: int = tuning.NEARBY_WALK_STEPS
) -> list[list[int]] | None:
    """Shortest walk from start to any cell within reach of target; [] if already within reach."""
    if math.dist(start, target) <= tuning.REACH_CELLS:
        return []
    previous, steps = bfs(start, blocked, limit)
    goals = [c for c in steps if math.dist(c, target) <= tuning.REACH_CELLS]
    if not goals:
        return None
    cell = min(goals, key=lambda c: (steps[c], math.dist(c, target), c))
    path = []
    while cell != start:
        path.append([cell[0], cell[1]])
        cell = previous[cell]
    return path[::-1]


def plan_walk(state: dict, targets: list[tuple[int, int]]) -> list[list[int]] | None:
    """The stranger's walk to reach each target, nearest first; None if one cannot be reached."""
    if not targets:
        return []
    blocked = blocked_cells(state)
    position = (state["player"]["x"], state["player"]["y"])
    path: list[list[int]] = []
    remaining = list(dict.fromkeys(targets))
    while remaining:
        options = [
            (route, target)
            for target in remaining
            if (route := path_to_reach(position, target, blocked, tuning.NEARBY_WALK_STEPS * 2)) is not None
        ]
        if not options:
            return None
        route, target = min(options, key=lambda option: len(option[0]))
        path += route
        position = tuple(route[-1]) if route else position
        remaining.remove(target)
    return path


def open_cells_near(state: dict, x: int, y: int, cleared: set[str], count: int) -> list[tuple[int, int]]:
    """Nearest open cells around (x, y), preferring ones without loose objects, for dropping pieces."""
    blocked = obstacle_cells(cleared)
    occupied = {(o["x"], o["y"]) for o in state["objects"].values() if o["holder_id"] is None}
    ring = sorted(((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)), key=lambda d: (math.hypot(*d), d))
    cells = [(x + dx, y + dy) for dx, dy in ring if walkable((x + dx, y + dy), blocked)]
    free = [c for c in cells if c not in occupied] + [c for c in cells if c in occupied]
    return [free[i % len(free)] for i in range(count)] if free else [(x, y)] * count


def line_of_sight(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if no building stands between the two cells (Bresenham line)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while (x0, y0) != (x1, y1):
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy
        if (x0, y0) != (x1, y1) and (x0, y0) in WALLS:
            return False
    return True
