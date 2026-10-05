"""Prepare a durable soak-test fixture in the explicitly selected development database.
Never accepts demo.sqlite3; this is test setup, not an endpoint or gameplay rule.
"""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import cast
import combat
import routes_world
import store

if not os.environ.get("DATABASE_PATH") or store.DB_PATH.name == "demo.sqlite3":
    raise SystemExit("Select an isolated profile database with DATABASE_PATH.")
state = routes_world.create_run(routes_world.NewRun(mode="developer"))
state["player"].update(x=48, y=60, health=100000)
state["player"]["conditions"] = [{"kind": "ache", "area": "arm", "treated": 1}]
for npc_id, cell in zip(["npc_bren_marr", "npc_oren_dast", "npc_roderic_vale"], [(48, 58), (46, 60), (50, 60)]):
    person = cast.find(state["npcs"], npc_id)
    person.update(x=cell[0], y=cell[1], health=100000)
    person["conditions"] = [{"kind": "ache", "area": "arm", "treated": 1}]
combat.start(state, ["npc_bren_marr", "npc_oren_dast", "npc_roderic_vale"], 0, "spar", lethal=False)
with store.db() as connection:
    store.save_checkpoint(connection, state)
print(state["run_id"])
