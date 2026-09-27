# Project setup

Open **C:\Users\Burry\Documents\time-travel** in Codex. Open the `project.godot` in that same folder in Godot. This is already the correct shared project root.

The current design is `GAME_DESIGN_GUIDE.md`. The older DOCX documents remain background reference. The game premise remains: arrive from the future with only your knowledge, use it to get inside the city, then use playtest results to decide how the larger game develops.

## Folder layout

```text
time-travel/
  project.godot             existing Godot project
  addons/godot_ai/          existing editor MCP addon
  docs/                    design and setup documents
  scenes/                  future game scenes
  scripts/                 future GDScript
  ui/                      future interface scenes
  assets/                  future game-ready art and sound
  backend/                 future Python simulation and AI service
  data/                    future seeds, migrations and local saves
  evals/                   future evaluation fixtures and runner
  config/                  future non-secret configuration
  tools/                   future development launch scripts
```

Milestone 0 now adds `scenes`, `scripts`, `assets`, `backend`, `data`, and `tools` under this same root. `ui`, `evals` and `config` remain planned. There is no need to add another folder as a separate Codex project or move `project.godot` into `client_godot`.

`docs/.gdignore` keeps design files out of Godot's resource import. Add a `.gdignore` to non-client backend/data/eval/tool directories when they are created. Keep provider credentials and save databases out of Godot resources and exports.

## Godot MCP connection

1. Open this project's `project.godot` in Godot and leave the editor running.
2. Under **Project > Project Settings > Plugins**, keep **Godot AI** enabled. It was already enabled when inspected.
3. In the **Godot AI** dock, select **Codex**. If the configuration is missing or mismatched, press **Configure**.
4. Refresh/restart Codex's MCP connection if the tools remain unavailable after configuration. Keep this same project folder open.
5. Before editing scenes through MCP, verify that its connected project path is `C:\Users\Burry\Documents\time-travel`.

At the 24 September 2026 inspection, the user Codex config already had an enabled `godot-ai` server entry. Its attach command targeted HTTP port **8001** and WebSocket port **8002**. No Godot process or listeners on those ports were observed at that time; no live MCP connection was claimed or configuration changed. The addon manages its own ports, so use its displayed status if they change.

Adding a project subfolder does not connect MCP. The addon is an editor tool; the future Python simulation service is a separate runtime system. The GDD assigns that service its own configurable local port, initially **8765**, to avoid using the addon's ports.

References: [Codex MCP configuration](https://developers.openai.com/codex/mcp); installed addon `addons/godot_ai/README.md` and `addons/godot_ai/clients/codex.gd`.

## Current phase

See the milestone plan in [GDD.md](../GDD.md) section 11. As of 27 September 2026 the project is starting M0 (clean slate), followed by M1 (world data and intent plumbing) before any AI integration. [FEEL_PASS.md](FEEL_PASS.md) still documents the current controls, startup, and manual tests for the existing build.
