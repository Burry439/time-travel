"""The item library (D-49): the same thing isn't painted twice.

Every picture painted for a made thing (its world sprite, its held view, its worn sheet) is kept under the thing's
signature: the method it was made by, its name, materials, gear class, flags, and size and weight to a tenth. When
anyone (in any journey on this server) makes something with exactly the same signature, it gets those pictures at
once, with no image call. Anything that differs in any of those is a different thing and is painted anew.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

VIEWS = ("world", "held", "worn")


def library_dir() -> Path:
    """Beside the journey's own pictures (data/assets/library)."""
    import attempts  # attempts imports library
    return attempts.ASSET_DIR / "library"


def signature(obj: dict, precedent_key: str | None = None) -> str:
    """Everything that makes two made things the same thing. A near-match is a different thing."""
    record = obj.get("gear") or {}
    key = {"method": (precedent_key or "").strip().lower(),
           "name": " ".join((obj.get("base_name") or obj.get("name") or "").lower().split()),
           "materials": sorted(m.lower() for m in obj.get("materials") or []),
           "gear": [record.get("kind"), record.get("class"), sorted(record.get("covers") or [])],
           "flags": sorted(obj.get("flags") or []),
           "length": round(float(obj.get("length_m") or 0), 1), "mass": round(float(obj.get("mass_kg") or 0), 1)}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:20]


def lookup(connection: sqlite3.Connection, sig: str, view: str) -> Path | None:
    row = connection.execute("SELECT file FROM item_library WHERE signature=? AND view=?", (sig, view)).fetchone()
    if row is None:
        return None
    path = library_dir() / row["file"]
    return path if path.exists() else None


def use(connection: sqlite3.Connection, sig: str, view: str, destination: Path) -> bool:
    """Copy the library's picture for this thing into place; True if there was one."""
    source = lookup(connection, sig, view)
    if source is None:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    connection.execute("UPDATE item_library SET uses=uses+1 WHERE signature=? AND view=?", (sig, view))
    return True


def remember(connection: sqlite3.Connection, sig: str, view: str, painted: Path, record: dict) -> None:
    """Keep a freshly painted picture for everyone who makes the same thing later."""
    if not painted.exists():
        return
    library_dir().mkdir(parents=True, exist_ok=True)
    name = f"{sig}_{view}.png"
    shutil.copyfile(painted, library_dir() / name)
    connection.execute("INSERT OR REPLACE INTO item_library (signature,view,file,record_json,uses) VALUES "
                       "(?,?,?,?,COALESCE((SELECT uses FROM item_library WHERE signature=? AND view=?),0))",
                       (sig, view, name, json.dumps(record), sig, view))
