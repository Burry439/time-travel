# Graphics and gameplay feel pass — 26 September 2026

The current priority is enjoyable exploration and clear interaction. `GAME_DESIGN_GUIDE.md` remains the design guide. This pass does not add the AI judge or replace original intentions with scripted quests.

## Play this version

Open the existing `project.godot`. Run `tools/run_m0.ps1` if the local backend is not running, then press F5. Select **Begin a journey** for the new map geometry. Earlier saves are preserved and can resume with their original collision rules; they do not gain new building/tree collisions.

| Control | Action |
| --- | --- |
| WASD / arrows | Walk in eight directions |
| Shift | Run |
| E | Pick up a loose object; inspect owned objects or meet a nearby person |
| F | Inspect the highlighted target |
| Tab | Cycle targets when several are in reach |
| I | Open/close belongings; inspect or put down an item |
| J | Open/close the journal |
| Escape | Close a panel or pause |
| Mouse wheel | Camera zoom, also adjustable in Pause |
| F3 | Developer overlay, only in Developer playtest |

## What changed

- Walk 180 px/s and run 288 px/s, 25% faster. Short acceleration and deceleration, normalized diagonals, back-facing upward diagonals, animation driven by distance actually moved, quiet varied footsteps, and fading foot dust.
- More responsive camera with gentle lookahead. Zoom and volume settings persist. A 1280×720 design resolution keeps the interface within the screen as the window resizes.
- Smaller HUD, contextual interaction ring and prompt, pickup feedback, inventory with item images, local inspection, recent-action journal, and pause/settings menu. Returning to title drains pending movement and requests a save checkpoint.
- Removed the old command-entry panel from normal play. Quick take/drop actions use existing authoritative validation internally. The old parser and canned Hessa agreement remain legacy backend code, not the exposed gameplay loop.
- Larger buildings with ground-level sorting anchors. Six building footprints and nineteen tree trunks are authored in the scene and shared with the backend through `data/world_geometry.json`. Characters can pass behind tall artwork.
- New generated oak/cypress/shrub/rock artwork, gentle foliage sway, finer muted terrain grain, feathered paths, city sign, actor shadows, subtle NPC breathing, and nearby nameplates. The gate artwork is preserved.
- Movement buffers sixteen cell crossings rather than stopping at four. Idempotent retries and reconciliation handle lost responses. Backend checkpoints every sixty-four events bound replay cost. Long outages still pause prediction.

## Manual acceptance

1. Start a new journey. Move in all eight directions, reverse direction, stop, hold Shift, and push against a building or tree. Upward diagonals should show the player's back; blocked movement should stop walking animation.
2. At the southern start, pick up a branch with E. Cycle targets with Tab. Open I, inspect and put down the branch. Walk away and back. Return to title, continue, and confirm its location persists.
3. Walk north past the inn to the gate, with detours to the smithy and carpenter. Judge camera distance, character readability, building scale, path clarity, and front/behind sorting. Try wheel and pause-menu zoom.
4. Press Escape while moving. Change sound volume, resume, and resize the window. Panels should remain readable and fully onscreen.
5. Approach different NPCs. Their names and roles should be clear. Conversations are explicitly unavailable in this presentation build; no scripted task is presented as AI behavior.

## Verification

Backend regression coverage includes seed, gate permissions, replay, idempotency, movement timing, diagonal corner rules, ownership, object operations, and geometry. Run from `backend`: `.venv/Scripts/python.exe -m pytest tests -q`.

`tools/smoke_feel.gd` exercises actual Godot pickup, inventory, dropping, upward diagonal running, pause, save/reload, modal bounds, and the inn's physical footprint. It creates a disposable test run without replacing the player's last-run pointer. Run Godot with `--headless --path . --script tools/smoke_feel.gd`.

Screenshots in `docs/screenshots` were captured from the running game and inspected. Both OpenGL Compatibility and the project's default D3D12 Forward+ renderer were exercised. Add `-- --capture` with a real renderer to refresh screenshots.

## Still unfinished

NPCs have individual sprites and subtle idle movement, but no proper directional walking, work, gesture, or interaction animations. NPC routines, dialogue, player-created objects, and the AI judge remain unfinished. Decorative vegetation is not harvestable. Buildings have no interiors. Normal mode does not yet provide a finished way to persuade the guards to admit the player.

These gaps matter to the eventual feeling of a living world. This pass improves controls, interaction friction, spatial readability, and feedback so they can be playtested separately.

## Art and implementation

New asset: `assets/generated/village_foliage.png`, created with the built-in image generation tool and copied into the project. Godot AtlasTexture regions select the sprites without modifying pixels. The actual atlas is 1280×1280; regions were adjusted after visual inspection. The prompt is recorded in `docs/FOLIAGE_PROMPT.txt`.

`tools/build_polish_scene.py` authors editor-visible nodes. Hand edits to its generated sections may be overwritten if it is rerun. Runtime NPCs use authoritative save data; NPCPreview shows their starting positions in the editor. Ground detail scripts use `@tool`, so the roads are also visible while editing.

References: [Godot Camera2D](https://docs.godotengine.org/en/stable/classes/class_camera2d.html), [Godot CharacterBody2D](https://docs.godotengine.org/en/stable/classes/class_characterbody2d.html).
