# Milestone 2: Try Something physical-action slice

**Historical prototype note.** This documents the bounded command parser built before the intention-first design was agreed. [GAME_DESIGN_GUIDE.md](../GAME_DESIGN_GUIDE.md) is now the working guide. The scripted Hessa task and recognized-verb flow are not the intended final interaction model.

This playable slice gives the future traveler a deterministic way to inspect and manipulate ordinary materials. It does **not** solve entry to the city. The knowledge-based gate solution remains Milestone 3. Milestone 1's persistent NPC decisions and dialogue are not implemented yet; Hessa's single work offer is a bounded, authored interaction so the agreement and transfer rules can be tested now.

## Run

Start the backend with `./tools/run_m0.ps1` from this project root, then run `scenes/main.tscn` in Godot. Start a **new run**: seed version 2 supplies the new road props, while an older saved run keeps its original seed. Press **E** or **TRY SOMETHING** to pause movement, select targets in reach, enter an action, and press **DO IT**. The panel shows the outcome, two recent journal entries, and Hessa's agreement status. The HUD lists carried objects. The seven prop sprites are authored in `scenes/main.tscn` under `M2Objects`, so they are visible in the editor; runtime updates their positions after actions.

The parser accepts up to three ordered steps separated by `then`. It recognizes `inspect`, `take`, `drop`, `give`, `tie`, `untie`, `fill`, `pour`, and the specific `ask Hessa for work` offer. It requires selected, named targets and never infers theft, permission, tools, or an invention effect. Unsupported and unclear actions consume no simulation time. A successful earlier step persists if a later step fails. Each accepted step and result is saved as an event; request IDs deduplicate retries, version checks reject stale requests, and checkpoints can accelerate replay. The API is intentionally conservative rather than pretending arbitrary prose is understood.

## Manual test

1. Start a new normal run. Near the spawn, press **E**. Select `branch_a`, enter `inspect branch a`, and confirm its mass, condition, owner and capabilities appear. Enter `invent a teleporter`; confirm **UNSUPPORTED**, no material change, and no added simulation time (F3 trace in developer mode can show time).
2. Select both branches and enter `take branch a then take branch b`. Both should disappear from the road and appear in the HUD. Select `cord_a`, `take cord a`, then select a branch and the cord and enter `tie branch a with cord a`. Trying to drop the tied branch should fail. Select the cord and enter `untie cord a`, then dropping the branch should work.
3. For the Hessa path, start another new run or carry both branches north-west to Hessa at the inn. Try `take bucket hessa` before an agreement: it must be blocked because she owns it. Select Hessa and enter `ask Hessa for work`. This creates an accepted task but no bucket permission yet. Asking again gives no extra benefit. Select a branch and Hessa and enter `give branch a to Hessa`; select the other branch and enter `drop branch b` beside her. The journal should show **fulfilled**. Now `take bucket hessa`, `fill bucket hessa` near the trough, and `pour bucket hessa` should work. The bucket remains Hessa's property even while carried.
4. Close and reopen the game, choose **RESUME LAST RUN**, and verify carried items, dropped positions, agreement status and journal survive. The city gate remains closed in normal mode.

## Current boundaries

The available physical operations are a small authored subset, with one live agreement and no autonomous NPC decision-making, invention judge, combat, crafting economy, or city-entry permission. `give` is currently accepted only for branches under Hessa's accepted task. The water trough begins with 80 L; filling moves 1 L to the bucket, and pouring records it as spilled so the quantity is conserved. The object preview positions and generated art live in the Godot scene, while the backend owns the canonical material state. The generated source atlases are in `assets/source/generated/`; `tools/slice_m2_art.py` recreates the six individual prop textures.

Backend verification: run `./.venv/Scripts/python.exe -m pytest -q tests` from `backend`. With the backend running, `Godot_v4.7.2-stable_win64_console.exe --headless --path . --script res://tools/smoke_m2.gd` creates a fresh run, opens Try Something, picks up the starting branch, and checks the on-screen result without changing the user's last-run pointer.
