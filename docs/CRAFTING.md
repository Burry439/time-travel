# Try Something

Press **T** (or Enter) in the world and describe, in your own words, what you want to do with what you carry and whatever or whoever is within reach. You can describe several things in one go ("sharpen the branch into a spear with the flint, then stab Tomas with it"): they happen in order, and if one fails the rest do not happen. The chips show them; clicking one is optional. There are no command words. The AI judge decides what happens, and code checks the result before anything changes.

## What you can do

- **Make** something new: "lash the flint to the branch with the vine to make a spear". The new object goes in your bag with its own history, and a picture is painted for it (a pulsing stand-in shows until it arrives).
- **Take** things, including other people's: "grab Tomas's plank". It works, but the game records it as theft. People don't react yet; they will in a later version.
- **Cut, break or fell** something: "cut down the young birch with the flint shard".
  - The tree falls over and leaves pieces (trunk, branches, stump). Each gets its own picture. Anything up to 20 kg can be picked up.
  - A felled map tree no longer blocks the path.
  - Big oaks and cypresses need real tools and hours of work. The three saplings (by the road start, east of it, and near the craftsmen's row) are realistic with a flint.
- **Attack** someone within reach: "thrust the spear into …". The result is a miss, a wound or a death, depending on the weapon and how alert they are. A death is permanent: the body stays down and the name shows "(dead)". Witnesses are recorded for later versions.

Code always checks:

- You can't invent materials, and nothing weighs more than what went into it.
- Nothing burns or is magnetic without a real cause.
- People must be within reach, and a weapon must actually be at hand.

## Materials in the world

- **The south road start:** branches, cord, stones, flint, flat stone, dry grass, reeds, vine, bark, resin, hazel rod, pine cones and a birch sapling.
- **The rest of the map:** feathers, wool, a bone, a gourd, wet clay, a pot shard, straw, leather, a **bent iron nail** and a **rusty horseshoe** (iron!), charcoal, chalk, bramble, burdock leaves, birch bark, a heavy log, and two more saplings.
- **Everywhere:** all 19 big trees.
- **Owned by NPCs:** Hessa's bucket and Tomas's plank.

To add your own, edit `data/content/world_objects.json`. Then run:

```powershell
backend/.venv/Scripts/python.exe tools/generate_material_art.py
```

Start a **new journey** to see new content; existing journeys keep their original world.

## Set up the AI (once)

1. Put your key in **`backend/.env`**, never in `.env.example`, which is shared in git: `OPENAI_API_KEY=...`
2. Restart the backend from the project root:
   ```powershell
   ./tools/stop_m0.ps1; ./tools/run_m0.ps1
   ```
3. The title screen stops saying "AI crafting is off".

## Debugging what the model did

Start a **Developer playtest**.

- **Every result card** ends with a developer trace:
  - The model, latency, tokens and any errors
  - What the model proposed vs. what the validator committed, with a note for every change
  - Buttons to show the raw model JSON, the exact context sent to it, and the committed object
- **F4** (or the F3 panel's *AI traces* button) lists the last 10 attempts, sprite jobs with their prompts and errors (with *Retry painting*), the model-call log, and the judge's full system prompt.
- The same data is available at `http://127.0.0.1:8765/runs/<run_id>/traces`.

## Settings (`backend/.env`)

| Setting | Default | Notes |
| --- | --- | --- |
| `MODEL_JUDGE` | `gpt-6-luna` | `gpt-6-sol` is about 15× the cost; switch only if evals show a need |
| `JUDGE_REASONING` | `low` | `none`, `low`, `medium`, `high` |
| `MODEL_IMAGE` | `gpt-image-2.5-flare` | Falls back to `MODEL_IMAGE_FALLBACK` (`gpt-image-2`) |
| `IMAGE_QUALITY` | `medium` | |
| `IMAGES` | `on` | `off` keeps stand-in pictures |
| `MAX_MODEL_CALLS_PER_RUN` | `200` | Spend safety valve |
| `AI_MODE` | `live` | `off` disables AI; `stub` uses a fake judge and stand-in pictures, with no key and no cost |

## Tests

- **Backend:** `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
- **Godot flow, no key needed:**
  1. Start the backend with `$env:AI_MODE='stub'; ./tools/run_m0.ps1`.
  2. Run `Godot_v4.7.2-stable_win64_console.exe --headless --path . --script res://tools/smoke_craft.gd`.
  3. Restart the backend normally afterwards.
- **Live judge quality** (costs about a cent per run): `backend/.venv/Scripts/python.exe evals/run_craft_evals.py --runs 3`. It runs 19 cases, including bad physics, ownership, felling, attacks and prompt injection, and writes a report to `evals/results/`.
