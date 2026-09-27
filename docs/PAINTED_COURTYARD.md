# Painted inn courtyard prototype

This records the first visual review point in the playable city-gate demo plan. The newer full-cast village pass is described in [LIVING_VILLAGE.md](LIVING_VILLAGE.md). The player's journey still starts on the south road. Run `tools/run_m0.ps1` if needed, press F5 in Godot, start a new journey, and walk north to Hessa's inn. The local backend owns the saved world.

The traveler and Hessa use a reusable Godot cutout rig. The traveler has eight painted views, including four distinct diagonal orientations; Hessa has four cardinal views. Head, torso, arms, and legs are sampled as separate regions from the generated transparent turnaround art. Walking and running animate the limb layers according to distance traveled; idle breathes subtly; pickup and greeting trigger short gestures. Both adults are 108 pixels tall at camera zoom 1.0. The player has normalized eight-direction movement, Shift run, footstep sound, collision, pickup, inventory, and save behavior.

The September feel pass raised walking to 230 pixels/second and Shift running to 368 pixels/second, shortened acceleration and stopping time, reduced camera lead, and removed camera smoothing. The local backend uses matching movement rates when advancing saved simulation time. The four diagonal illustrations were generated from the same traveler reference and assigned to southeast, southwest, northwest, and northeast; diagonal movement now selects and animates the corresponding view.

The inn has been redrawn with a larger entrance. Its world position and collision footprint remain the same; the art bottom aligns to the building's ground anchor. The courtyard ground is muted to help the characters read. The city gate artwork is unchanged. This first sample covered the traveler and Hessa; the subsequent village pass extended painted rigs to the full cast.

Open `scenes/inn_courtyard_preview.tscn` to inspect the authored sample in the Godot editor. The playable map is `scenes/main.tscn`. Use the Pause menu to set zoom to 1.0 for the intended scale review. At the inn, judge the doorway against Hessa, walk in each direction, run and stop, inspect Hessa, and pick up an object to see the pickup gesture. Record any seam, limb, scale, or lighting problems before applying this rig and style to the other NPCs.

Generated assets saved in the project:

- `assets/generated/traveler_painted_turnaround.png`
- `assets/generated/traveler_painted_diagonals.png`
- `assets/generated/hessa_painted_turnaround.png`
- `assets/generated/inn_painted_v2.png`

All four were created with the built-in image generation tool. The character prompts used the existing traveler, Hessa, and inn art as identity and style references. The first character sheets requested transparent four-view turnarounds; the diagonal sheet requested distinct southeast, southwest, northwest, and northeast three-quarter views with the same traveler, height, outfit, and lighting. The inn prompt used its previous art and Hessa as references, requesting the same orientation, recognizable timber and terracotta design, a larger usable doorway, a transparent cutout, and upper-left sunlight. Existing source pixels were not altered; Godot AtlasTexture regions assemble the new characters at runtime.

The new village collision map is geometry version 3. Six building footprints now reach the visible wall edges. The backend checks the same blocked cells, while version 2 saves keep their original map data. `tools/smoke_building_edges.gd` tests the player against all four sides of all six buildings. Start a **new journey** to judge the updated collision map; a resumed version 2 journey keeps its old footprint rules.

Verification: `tools/smoke_feel.gd` checks all eight painted views, pickup/drop persistence, diagonal running, pause, save/reload, and building collision in the actual Godot scene, and captures `docs/screenshots/painted-diagonal-run.png`. `tools/smoke_building_edges.gd` checks all 24 approaches to the six buildings. `tools/smoke_responsiveness.gd` measures sustained running and movement queue pressure; the latest local run reached 365.8 pixels/second with zero stopped frames and no queued moves. `tools/capture_courtyard.gd` captures the editor sample. The backend regression suite passes from `backend/` with `python -m pytest tests -q`.

This is a **playable visual-direction prototype**, not an approved full-cast animation standard yet. A more aggressive side-leg swing exposed a gap, so the current side walk uses smaller motion and a hip overlap. The generated alternative walk sheet repeated the same leading leg and was rejected. The remaining question for playtesting is whether the restrained gait reads well enough at gameplay size, especially on stop/start and while running. If it still reads as sliding, the next art pass needs intentionally drawn alternating contact poses before we copy this animation to the other characters. Static screenshots cannot settle that question.
