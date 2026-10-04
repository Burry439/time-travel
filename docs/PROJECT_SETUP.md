# Run the demo

The working design is [GDD.md](../GDD.md). Open `project.godot` from the repository root in Godot 4.

On Windows, from the repository root:

```powershell
uv sync --native-tls --project backend
.\tools\run_demo.ps1
```

Set `OPENAI_API_KEY` in `backend/.env`; it stays on the backend. The launcher checks the configured model and credentials, starts a hidden local backend on port 8767, then opens the game. Set `GODOT` or pass `-GodotPath` if your executable is elsewhere. Use `-BackendOnly` to run the backend alone, or `-Port 8768` if another process uses the port.

This branch's demo saves use `data/open-ended-demo.sqlite3`. The original `data/demo.sqlite3` is preserved. Saves from before seed 14 are retired with a clear new-journey message, never deleted.

For offline pipeline checks, use `.\tools\run_demo.ps1 -Stub`. Stub mode supplies deterministic test responses and does not demonstrate real AI judgment.

```powershell
.\tools\check.ps1 -Full
backend\.venv\Scripts\python.exe evals\run_open_ended_live.py --runs 2
```

The full check uses a temporary database and its own backend on port 8766. Live evaluations use transient in-memory worlds; they do not change your saved journeys. Evaluation reports and branch verification are described in [OPEN_ENDED_DEMO.md](OPEN_ENDED_DEMO.md).

To stop a backend started by the demo launcher, use the PID in `data/demo-8767.pid` and verify that process is this launcher's Python/uvicorn process before stopping it. Restart it after changing environment configuration or switching branches.

The preserved pre-change code is on `codex/demo-baseline` (checkpoint 994def4); the implementation is on `codex/open-ended-demo`. After saving any edits, `git switch codex/demo-baseline` returns to that checkpoint.
