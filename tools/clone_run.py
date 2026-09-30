"""Copy a saved journey (its run row, events and checkpoints) under a new id, for reproducing a player's problem
without touching their journey. Prints the new id.

    backend/.venv/Scripts/python tools/clone_run.py RUN_ID [--mode developer]
"""
from __future__ import annotations

import argparse
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--mode", default=None)
    args = parser.parse_args()
    connection = sqlite3.connect(ROOT / "data" / "demo.sqlite3")
    connection.row_factory = sqlite3.Row
    new_id = uuid.uuid4().hex
    run = dict(connection.execute("SELECT * FROM runs WHERE id=?", (args.run_id,)).fetchone())
    run["id"] = new_id
    if args.mode:
        run["mode"] = args.mode
    connection.execute(f"INSERT INTO runs ({','.join(run)}) VALUES ({','.join('?' * len(run))})", list(run.values()))
    for table in ("events", "checkpoints"):
        rows = [dict(r) for r in connection.execute(f"SELECT * FROM {table} WHERE run_id=?", (args.run_id,))]
        for row in rows:
            row["run_id"] = new_id
            if table == "checkpoints":  # The saved state names its journey.
                row["state_json"] = row["state_json"].replace(args.run_id, new_id)
            if table == "events" and row.get("request_id"):
                row["request_id"] = f"clone:{row['request_id']}"
            connection.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                               list(row.values()))
    connection.commit()
    print(new_id)


if __name__ == "__main__":
    main()
