# Milestone 0: playable foundation

**Roadmap note.** This records the original foundation milestone. The milestone numbering and later scope were superseded by [GAME_DESIGN_GUIDE.md](../GAME_DESIGN_GUIDE.md), which is the working guide for the intention-first game.

The original idea remains the target: the player comes from the future with useful knowledge and must get inside the city. This milestone establishes the map, movement, saved state and the city-entry trigger. It is not yet the knowledge puzzle. The first full knowledge-based playable slice is Milestone 3.

## Run it

1. In PowerShell, from the existing `time-travel` project root, run `./tools/run_m0.ps1`. The script starts a local Python backend on port 8765 and reports when `/health` responds. On first use, `uv` may need to install the backend packages from `backend/uv.lock`.
2. Open the same folder's `project.godot` in Godot 4.7 or newer. Press **F6** with `scenes/main.tscn` open, or **F5** to run the main scene.
3. Choose **START** for the ordinary locked-gate map, or **START DEVELOPER MODE** to inspect state and open the gate for the entry-trigger test.

To inspect the map without running it, open `scenes/main.tscn`, switch to the **2D** workspace, select **Map > Ground** in the Scene tree, and press **Shift+F** to frame the map. The scene now contains the ground, buildings, tiled walls, gate, collisions, player and eight NPC starting previews. The `NPCPreview` group hides when Play starts; actual NPC actors use the backend's current positions.

Movement is **WASD** or the **arrow keys**, including diagonals; hold **Shift** to run. **F3** toggles the developer trace in developer mode; **Esc** returns to the menu. The game stores the last run ID locally and the backend saves its event history in `data/demo.sqlite3`. **RESUME LAST RUN** loads the saved state after closing and reopening the game.

## What to test manually

1. Start normally. Check the objective and future-origin introduction, generated traveler/terrain/building art, and all eight distinct named NPCs at their authored starting anchors. Walk cardinally and diagonally, then hold Shift to run. Upward diagonals should show the player's back; diagonal movement should not be faster than straight movement at the same gait.
2. Walk toward the gate. The wall and closed gate must physically stop the character. Walk along the wall and try its far edges; no route around the map boundary should enter the city.
3. Quit, reopen, and choose **RESUME LAST RUN**. Position and gate state should match the last accepted movement, with no duplicate objective event.
4. Start Developer Mode. Press **F3**, inspect the run ID, event count, tick, position and gate state. Use **OPEN GATE (TEST)**, walk north through the gate, and confirm the city-entry screen appears exactly once. Close and resume; the completed run remains completed.
5. Check the menu's backend-offline message with `./tools/stop_m0.ps1`, then restart it with `./tools/run_m0.ps1`. Game startup should recover without creating a fake successful run.

The developer gate button exists only to exercise M0 geometry and victory. Normal entry requires knowledge, evidence and NPC consequences in Milestone 3. The feel pass adds directional player walking, Shift-running, a wider camera, larger character rendering, distinct NPC sprites, and generated terrain and building facades. The static map, collisions, player and NPC starting previews are visible as nodes in `scenes/main.tscn`; backend-driven NPC actors appear when a run starts. NPC behavior belongs to M1. See [FEEL_PASS.md](FEEL_PASS.md) for the temporary visual acceptance gate before M1.

## Developer checks

Run the backend tests from `backend` with `uv run --native-tls --group dev python -m pytest -q tests`. The FastAPI service exposes `/health`, `/runs`, `/runs/{id}`, `/runs/{id}/events`, `/runs/{id}/move` and a developer-only gate command. Accepted movement is appended to SQLite, and saved state is rebuilt by replaying those events. `request_id` prevents duplicate commits; `expected_version` rejects stale commands.
