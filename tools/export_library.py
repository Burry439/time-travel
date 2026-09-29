"""The item library to a folder, or back (D-49), so a shipped build starts with everything already painted.

    backend/.venv/Scripts/python.exe tools/export_library.py            # data/assets/library/index.json
    backend/.venv/Scripts/python.exe tools/export_library.py --import   # load index.json into this database

The pictures already live in data/assets/library/ (never committed: data/assets is local). Export writes the index
beside them; import reads it into the item_library table of the database on this machine.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import library  # noqa: E402
import store  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import", dest="load", action="store_true")
    args = parser.parse_args(argv)
    index = library.library_dir() / "index.json"
    with store.db() as connection:
        if args.load:
            rows = json.loads(index.read_text(encoding="utf-8"))
            for row in rows:
                if (library.library_dir() / row["file"]).exists():
                    connection.execute("INSERT OR IGNORE INTO item_library (signature,view,file,record_json,uses) "
                                       "VALUES (?,?,?,?,0)", (row["signature"], row["view"], row["file"],
                                                              json.dumps(row["record"])))
            print(f"Loaded {len(rows)} library pictures from {index.relative_to(ROOT)}")
            return 0
        rows = [{"signature": r["signature"], "view": r["view"], "file": r["file"], "uses": r["uses"],
                 "record": json.loads(r["record_json"])}
                for r in connection.execute("SELECT * FROM item_library ORDER BY created_at")]
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"Wrote {len(rows)} library pictures to {index.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
