"""The gap log (D-65): deeds players tried that the world couldn't carry out, from the saved attempts.

    backend/.venv/Scripts/python.exe tools/gap_report.py [path/to/save.sqlite3 ...] [--all]

Reads each journey database's craft traces (the judge's proposal and the validator's ruling, saved with every
attempt) and lists:
- unsupported: the judge said the world can't represent it;
- unresolved: the judge proposed something the laws refused (with the law it broke);
- hollow: ruled a success but nothing changed (no effects, no typed change). Each is a building block the world
  may be missing.
With no paths it reads data/open-ended-demo.sqlite3 and data/demo.sqlite3. --all also lists every attempt's
category counts. Nothing is written.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPED = ("new_spec", "take_ids", "transform", "harm", "fill", "demonstration", "give", "install", "lift_out",
         "offer_trade", "gather", "treat", "equip", "drop_ids", "effects", "hurt_self")


def hollow(ruling: dict) -> bool:
    """A success with nothing to show for it."""
    if ruling.get("category") not in ("success", "partial_success"):
        return False
    return not any(ruling.get(field) for field in TYPED) and ruling.get("action") in ("other", None)


def report(path: Path) -> tuple[Counter, list[tuple[str, str, str]]]:
    counts, gaps = Counter(), []
    with sqlite3.connect(path) as connection:
        for (raw,) in connection.execute("SELECT trace_json FROM craft_traces ORDER BY created_at"):
            trace = json.loads(raw)
            ruling = trace.get("validator") or {}
            category = ruling.get("category")
            counts[category] += 1
            text = " ".join((trace.get("text") or "").split())[:110]
            if category == "unsupported":
                gaps.append(("unsupported", text, (ruling.get("reason") or "")[:120]))
            elif category == "unresolved":
                law = next((n for n in reversed(ruling.get("notes") or []) if n.startswith("Rejected")), "")
                gaps.append(("unresolved", text, law[:120] or (ruling.get("reason") or "")[:120]))
            elif hollow(ruling):
                gaps.append(("hollow", text, (ruling.get("reason") or "")[:120]))
    return counts, gaps


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = [Path(a) for a in args] or [ROOT / "data/open-ended-demo.sqlite3", ROOT / "data/demo.sqlite3"]
    for path in paths:
        if not path.exists():
            print(f"(no {path})")
            continue
        counts, gaps = report(path)
        total = sum(counts.values())
        print(f"\n{path.name}: {total} attempts, {len(gaps)} gaps")
        if "--all" in sys.argv:
            print("  " + ", ".join(f"{k}: {v}" for k, v in counts.most_common()))
        for kind, text, why in gaps:
            print(f"  {kind:11} {text}\n              {why}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
