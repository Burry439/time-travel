"""What players did in each training level (GDD D-59: every level is also a lab).

    backend/.venv/Scripts/python.exe tools/level_report.py [--level cup_of_water] [--db data/demo.sqlite3]

For each level in a track: journeys started and finished, the time a finished one took (against the level's
minutes), each step's time (from the step starting to the next, wall clock, cards included), the attempts made in
each step and how they went (with the reasons for failures), questions asked of the device, and players' ratings
and comments. Read from the saves (runs, events, feedback); nothing is changed.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import content  # noqa: E402
import store  # noqa: E402

STAMP = "%Y-%m-%d %H:%M:%S.%f"


def when(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.strptime(text if "." in text else text + ".000", STAMP)


def minutes(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def journey(connection: sqlite3.Connection, run_id: str, steps: list[dict]) -> dict:
    """One journey's steps: when each began, and the attempts and questions in it."""
    step, began = 0, None
    times: dict[int, float] = {}
    attempts: dict[int, list[dict]] = defaultdict(list)
    questions = 0
    rows = connection.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    for row in rows:
        at = when(row["created_at"]) if "created_at" in row.keys() else None  # noqa: SIM118 (a sqlite3.Row)
        began = began or at
        patch = store.payload_of(row).get("patch", {})
        for entry in (patch.get("journal") or {}).get("+", []):
            if entry.get("kind") == "craft":
                attempts[step].append(entry)
            elif entry.get("kind") == "device" and entry.get("question"):
                questions += 1
        moved = ((patch.get("tutorial") or {}).get("step") or {}).get("=")
        done = ((patch.get("tutorial") or {}).get("done") or {}).get("=")
        if (moved is not None or done) and at and began:
            times[step] = (at - began).total_seconds()
            began, step = at, (moved if moved is not None else len(steps))
    return {"times": times, "attempts": attempts, "questions": questions}


def report(connection: sqlite3.Connection, level: dict) -> list[str]:
    lines = [f"## {level['title']} ({level['id']}, {level['track']}, about {level['minutes']} min)"]
    runs = connection.execute(
        "SELECT id, created_at, completed_at FROM runs WHERE scenario=? ORDER BY created_at", (level["id"],)
    ).fetchall()
    done = [r for r in runs if r["completed_at"]]
    lines.append(f"Journeys: {len(runs)} started, {len(done)} finished.")
    if done:
        took = [(when(r["completed_at"]) - when(r["created_at"])).total_seconds() for r in done]
        lines.append(
            f"Time to finish: median {minutes(statistics.median(took))}, best {minutes(min(took))} "
            f"(target {level['minutes']}:00)."
        )
    played = [journey(connection, r["id"], level["steps"]) for r in runs]
    lines.append("")
    lines.append("| Step | Median time | Reached | Attempts (ok / failed) | Why attempts failed |")
    lines.append("| --- | --- | --- | --- | --- |")
    for index, step in enumerate(level["steps"]):
        times = [p["times"][index] for p in played if index in p["times"]]
        tries = [a for p in played for a in p["attempts"].get(index, [])]
        ok = sum(a.get("category") == "success" for a in tries)
        reasons = Counter(a.get("reason", "")[:70] for a in tries if a.get("category") != "success")
        why = "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common(2))
        lines.append(
            f"| {index + 1} {step['id']} | {minutes(statistics.median(times)) if times else '-'} | "
            f"{len(times)} | {ok} / {len(tries) - ok} | {why} |"
        )
    lines.append("")
    lines.append(f"Questions asked of the device: {sum(p['questions'] for p in played)}.")
    ratings = connection.execute(
        "SELECT rating, comment FROM feedback JOIN runs ON runs.id = feedback.run_id WHERE runs.scenario=?",
        (level["id"],),
    ).fetchall()
    if ratings:
        counts = Counter(r["rating"] for r in ratings)
        lines.append("Ratings: " + ", ".join(f"{name.replace('_', ' ')} {n}" for name, n in counts.most_common()) + ".")
        lines += [f"- “{r['comment']}”" for r in ratings if r["comment"]]
    return lines + [""]


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--level")
    parser.add_argument("--db", default=str(store.DB_PATH))
    args = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    levels = [lv for lv in content.LEVELS.values() if lv.get("track") and lv.get("steps")]
    for level in levels:
        if args.level in (None, level["id"]):
            print("\n".join(report(connection, level)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
