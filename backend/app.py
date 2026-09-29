"""The Time Travel RPG's local service: the event-sourced world and the routes Godot calls.

store.py keeps the save; routes_world.py moves the stranger and the clock; routes_craft.py and
attempts.py handle Try Something; rounds.py plays conversations and encounter rounds;
routes_minds.py lets people think. Models only propose: code decides what changes (GDD 8).
"""
from __future__ import annotations

from fastapi import FastAPI

import attempts
import crafting
import m2
import npc_sim
import rounds
import routes_craft
import routes_gear
import routes_minds
import routes_tutorial
import routes_world
import store
from ai import config as ai_config, decider, illustrator, judge, voice
from store import GEOMETRY_VERSION, NPCS, SEED_VERSION, WORLD_GEOMETRY, db, initial_state, load_run

app = FastAPI(title="The City Beyond", version="0.5.0")
for module in (routes_world, routes_craft, rounds, routes_minds, routes_gear, routes_tutorial):
    app.include_router(module.router)

# What tests and tools reach through this module.
__all__ = ["app", "attempts", "crafting", "m2", "npc_sim", "store", "ai_config", "decider", "illustrator", "judge",
           "voice", "GEOMETRY_VERSION", "NPCS", "SEED_VERSION", "WORLD_GEOMETRY", "db", "initial_state", "load_run"]
