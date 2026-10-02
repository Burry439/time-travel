"""Training (GDD D-59): the levels a player can choose, which are done and how long they took, and what players
said about each one. A level is done when its journey finished (store.finished: the story told to its end);
ratings are kept beside the journey, never in it, so they change nothing that replays."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import content
import store
import views

router = APIRouter(route_class=views.Shown)
TRACKS = [("basic", "Basics"), ("advanced", "Advanced"), ("test", "Developer")]
RATINGS = ("too_easy", "about_right", "confusing")
SECONDS = "CAST(strftime('%s', completed_at) AS INTEGER) - CAST(strftime('%s', created_at) AS INTEGER)"


class Feedback(BaseModel):
    rating: str
    comment: str = Field(default="", max_length=2000)


def catalogue() -> list[dict]:
    """Every level in a track, in order: what the Training screen shows of it."""
    order = [track for track, _ in TRACKS]
    levels = [level for level in content.LEVELS.values() if level.get("track") in order]
    levels.sort(key=lambda level: (order.index(level["track"]), level["order"]))
    keys = ("id", "title", "track", "order", "minutes", "teaches", "blurb")
    return [{key: level[key] for key in keys} | {"hidden": bool(level.get("hidden"))} for level in levels]


@router.get("/training")
def training():
    with store.db() as connection:
        rows = connection.execute(
            f"SELECT scenario, COUNT(*) AS done, MIN({SECONDS}) AS best FROM runs "
            "WHERE completed_at IS NOT NULL AND mode = 'normal' GROUP BY scenario"  # Not the lab's scripted runs.
        ).fetchall()
    done = {row["scenario"]: row for row in rows}
    levels = [
        level | {"done": level["id"] in done, "best_s": done[level["id"]]["best"] if level["id"] in done else None}
        for level in catalogue()
    ]
    return {"tracks": [{"id": track, "title": title} for track, title in TRACKS], "levels": levels}


@router.get("/runs/{run_id}/result")
def result(run_id: str):
    """How this journey's level went: done or not, and how long it took (seconds from start to done)."""
    with store.db() as connection:
        run = connection.execute(
            f"SELECT scenario, completed_at, {SECONDS} AS seconds FROM runs WHERE id=?", (run_id,)
        ).fetchone()
    if run is None:
        raise HTTPException(404, "Run not found")
    return {"level": run["scenario"], "done": run["completed_at"] is not None, "seconds": run["seconds"]}


@router.post("/runs/{run_id}/feedback", status_code=201)
def feedback(run_id: str, request: Feedback):
    if request.rating not in RATINGS:
        raise HTTPException(422, f"Rating must be one of {', '.join(RATINGS)}")
    with store.lock, store.db() as connection:
        if connection.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
            raise HTTPException(404, "Run not found")
        connection.execute(
            "INSERT INTO feedback (run_id, rating, comment) VALUES (?,?,?)", (run_id, request.rating, request.comment)
        )
    return {"saved": True}
