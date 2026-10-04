"""The walkable map: which cells are blocked, how to get from one cell to another, and what can be seen from
where. The stranger, people on their routines and people on their jobs all walk the same grid (GDD section 8):
the grid of the journey's map (data/maps, D-59)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

import content
import tuning
from shapes import State

Cell = tuple[int, int]


@dataclass(frozen=True)
class Grid:
    """Where nobody can walk on one map (`cell in grid`), and the part of it people keep to (`walk`: x0, y0, x1, y1,
    the far edges not included; on the village map, the ground below the city wall)."""

    blocked: frozenset[Cell]
    walk: tuple[int, int, int, int]

    def walkable(self, cell: Cell) -> bool:
        x0, y0, x1, y1 = self.walk
        return x0 <= cell[0] < x1 and y0 <= cell[1] < y1 and cell not in self.blocked

    def __contains__(self, cell: object) -> bool:
        return cell in self.blocked


def _cells(rectangles: Iterable[dict]) -> frozenset[Cell]:
    return frozenset(
        (cx, cy)
        for item in rectangles
        for bx, by, w, h in [item["cells"]]
        for cx in range(bx, bx + w)
        for cy in range(by, by + h)
    )


@cache
def walls(map_id: str) -> frozenset[Cell]:
    """Buildings block sight; trees do not."""
    return _cells(content.MAPS[map_id]["buildings"])


@cache
def _grid(map_id: str, cleared: frozenset[str]) -> Grid:
    plan = content.MAPS[map_id]
    standing = plan["buildings"] + plan["obstacles"]
    return Grid(_cells(item for item in standing if item["name"] not in cleared), tuple(plan["walk"]))


def cleared_obstacles(state: State) -> set[str]:
    """Geometry obstacles removed by play, such as felled trees."""
    return {
        o["geometry_name"] for o in state["objects"].values() if o.get("geometry_name") and o["condition"] != "usable"
    }


def placed_blocks(state: State) -> frozenset[Cell]:
    """Cells something has been put across (the log rolled over the road, D-65): nobody walks through them."""
    return frozenset(
        (o["x"], o["y"])
        for o in (state.get("objects") or {}).values()
        if o.get("blocks") and o.get("holder_id") is None and o.get("condition") != "destroyed"
    )


def _with_blocks(state: State, base: Grid) -> Grid:
    placed = placed_blocks(state)
    return Grid(base.blocked | placed, base.walk) if placed else base


def grid(state: State, cleared: Iterable[str] | None = None) -> Grid:
    """Buildings, obstacles (trees, rocks) not cleared away, and things put across a way: nobody walks through
    them. By default those this journey has cleared (felled trees no longer block)."""
    gone = cleared_obstacles(state) if cleared is None else cleared
    return _with_blocks(state, _grid(content.level(state)["map"], frozenset(gone)))


def standing_grid(state: State) -> Grid:
    """Every obstacle as the map was made, and anything since put across a way: what people's rounds go around."""
    return _with_blocks(state, _grid(content.level(state)["map"], frozenset()))


def walkable(cell: Cell, blocked: Grid) -> bool:
    return blocked.walkable(cell)


def bfs(start: tuple[int, int], blocked: Grid, limit: int) -> tuple[dict, dict]:
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


def route(start: tuple[int, int], goal: tuple[int, int], blocked: Grid) -> list[list[int]]:
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


NEXT_STEP_FAR = 400  # Steps: more than any walk across a map.


def next_step(start: tuple[int, int], goal: tuple[int, int], stop: float, blocked: Grid) -> tuple[int, int] | None:
    """One step toward being within stop of goal (someone on a job, a step per beat); None if there's no way. Near
    goals are searched first; a goal across the village gets the whole map (D-63: Darin, sent from his stall to pay
    Hessa at the inn, stood still for good, his errand longer than 60 steps)."""
    for reach in (60, NEXT_STEP_FAR):
        previous, steps = bfs(start, blocked, reach)
        goals = [c for c in steps if math.dist(c, goal) <= stop]
        if goals:
            break
    else:
        return None
    cell = min(goals, key=lambda c: (steps[c], math.dist(c, goal)))
    while previous.get(cell) not in (start, None):
        cell = previous[cell]
    return None if cell == start else cell


def path_to_reach(
    start: tuple[int, int], target: tuple[int, int], blocked: Grid, limit: int = tuning.NEARBY_WALK_STEPS
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


def plan_walk(state: State, targets: list[tuple[int, int]]) -> list[list[int]] | None:
    """The stranger's walk to reach each target, nearest first; None if one cannot be reached."""
    if not targets:
        return []
    blocked = grid(state)
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


def open_cells_near(state: State, x: int, y: int, cleared: set[str], count: int) -> list[tuple[int, int]]:
    """Nearest open cells around (x, y), preferring ones without loose objects, for dropping pieces."""
    blocked = grid(state, cleared)
    occupied = {(o["x"], o["y"]) for o in state["objects"].values() if o["holder_id"] is None}
    ring = sorted(((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)), key=lambda d: (math.hypot(*d), d))
    cells = [(x + dx, y + dy) for dx, dy in ring if walkable((x + dx, y + dy), blocked)]
    free = [c for c in cells if c not in occupied] + [c for c in cells if c in occupied]
    return [free[i % len(free)] for i in range(count)] if free else [(x, y)] * count


def line_of_sight(state: State, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if no building stands between the two cells (Bresenham line)."""
    buildings = walls(content.level(state)["map"])
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
        if (x0, y0) != (x1, y1) and (x0, y0) in buildings:
            return False
    return True


# --- The gate (only the village map has one) ----------------------------------------------------------------------


def gate(state: State) -> dict | None:
    """The map's gate: the wall's rows, the gap (cols), its middle, the approach and the guards' posts; None if this
    map has no gate."""
    return content.map_of(state).get("gate")


def in_zone(cell: Cell, zone: list[int]) -> bool:
    """Inside a zone [x from, x to, rows up to] (the gate's approach or its posts)."""
    x0, x1, top = zone
    return x0 <= cell[0] <= x1 and cell[1] <= top


def in_wall(gate: dict | None, cell: Cell) -> bool:
    """In the wall's rows: passable only through the gap, and only while the gate is open."""
    return gate is not None and gate["rows"][0] <= cell[1] <= gate["rows"][1]


def in_gap(gate: dict, cell: Cell) -> bool:
    return gate["cols"][0] <= cell[0] <= gate["cols"][1]


def breached(state: State, cell: Cell) -> bool:
    """A way through the wall itself: an obstacle in the wall's rows that play has cleared (brambles cut out of a
    gap in an old wall, D-59)."""
    gone = cleared_obstacles(state)
    plan = content.map_of(state)
    return any(item["name"] in gone and cell in _cells([item]) for item in plan["obstacles"])


def arrived(state: State, cell: Cell) -> bool:
    """The stranger has reached the map's inside (on the village map, the city): the journey's end."""
    inside = content.map_of(state).get("inside")
    return inside is not None and inside["rows"][0] <= cell[1] <= inside["rows"][1]
