# Crafting: make something new

Press **T** (or Enter) in the world. Describe, in your own words, what you want to make from things you carry or loose things within reach (the chips show them; clicking one is optional). The AI judge decides whether the method works. Code checks the result:

- You can't invent materials.
- You can't use someone else's property as a part.
- Nothing weighs more than what went into it.
- Nothing burns or is magnetic without a real cause.

A success puts a brand-new object in your bag, with its own history. A picture is painted for it in the background; a pulsing stand-in shows until it arrives.

The new road materials are near the start: a flint shard, a flat stone, dry grass, hollow reeds, a vine, a bark strip and pine resin, alongside the branches, cord and stone.

## Set up the AI (once)

1. Copy `backend/.env.example` to `backend/.env`.
2. Paste your key after `OPENAI_API_KEY=`. The file is git-ignored; never commit it.
3. Restart the backend from the project root in PowerShell:
   ```powershell
   ./tools/stop_m0.ps1; ./tools/run_m0.ps1
   ```
4. The title screen stops saying "AI crafting is off".
5. Optional: paint the new road materials once, then focus Godot so it imports them:
   ```powershell
   backend/.venv/Scripts/python.exe tools/generate_material_art.py
   ```

Existing journeys predate crafting. Choose **Begin a journey** or **Developer playtest** for a new one.

## Debugging what the model did

Start a **Developer playtest**.

- **Every result card** ends with a developer trace:
  - The model, latency, tokens and any errors
  - What the model proposed vs. what the validator actually committed, with a note for every change it made
  - Buttons to show the raw model JSON, the exact context sent to the model, and the committed object
- **F4** (or the F3 panel's *AI traces* button) shows the last 10 attempts, sprite jobs with their image prompts and errors (with *Retry painting*), the model-call log, and the judge's full system prompt.
- The same data is available at `http://127.0.0.1:8765/runs/<run_id>/traces`.

## Useful settings (`backend/.env`)

| Setting | Default | Notes |
| --- | --- | --- |
| `MODEL_JUDGE` | `gpt-6-sol` | `gpt-6-luna` is about 20× cheaper, but less careful |
| `JUDGE_REASONING` | `low` | `none`, `low`, `medium`, `high` |
| `MODEL_IMAGE` | `gpt-image-2.5-flare` | Falls back to `MODEL_IMAGE_FALLBACK` (`gpt-image-2`) |
| `IMAGE_QUALITY` | `medium` | |
| `IMAGES` | `on` | `off` keeps placeholders |
| `MAX_MODEL_CALLS_PER_RUN` | `200` | Spend safety valve |
| `AI_MODE` | `live` | `off` disables AI; `stub` uses a fake judge and stand-in pictures, with no key and no cost |

## Tests

- **Backend:** `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
- **Godot flow, no key needed:**
  1. Start the backend with `$env:AI_MODE='stub'; ./tools/run_m0.ps1`.
  2. Run `Godot_v4.7.2-stable_win64_console.exe --headless --path . --script res://tools/smoke_craft.gd`.
  3. Restart the backend normally afterwards.
- **Live judge quality** (costs a few cents): `backend/.venv/Scripts/python.exe evals/run_craft_evals.py --runs 3`. This runs 13 cases, including bad physics, owned property, fire, magnets and a prompt-injection attempt, and writes a report to `evals/results/`.
