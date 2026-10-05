# Brief for Codex: better combat and equipment (runs alongside Claude's D-65)

The user wants combat and equipment improved, and wants you to do it on your own, without asking them, while
Claude carries on with D-65 (the world's building blocks: signals, terrain, fire, processes) in the same repo.

## Set up (do this first)

1. Work in your own worktree and branch, never on Claude's:
   `git worktree add ../time-travel-combat -b codex/combat-gear codex/player-run-flow-fixes`
   Claude keeps committing to `codex/player-run-flow-fixes`. Don't commit there, and don't merge anything into `main`.
2. Read `AGENTS.md`, then in `GDD.md`: §6.8 Gear, bodies and remedies, rule V11 (no dice), V12 (the building
   blocks), and the decision rows D-49, D-51, D-59, D-62 and D-65. Then `backend/combat.py`, `backend/gear.py`,
   `data/content/gear.json`, `scripts/fight_view.gd`, `scripts/painted_actor.gd`, `scripts/player_input.gd`,
   `backend/tests/test_combat.py`, `backend/tests/test_gear.py`, `evals/run_gear_evals.py`,
   `tools/smoke_fight.gd`, `tools/smoke_gear.gd`, `tools/profile_combat.gd`.

## Step 1: find out what's actually wrong (evidence before building)

Don't assume; play it. Run fights live (the evals, the probes and a headless Godot run), and read the user's own
journeys in `data/demo.sqlite3` (read only: copy it with `tools/clone_run.py`, never write to it) for how their
fights and gear went. Write `docs/COMBAT_REVIEW.md`: a grade out of 100 for combat and for equipment, the concrete
problems with the evidence for each, ranked by how much they hurt play. Then fix them, biggest first.

Places to look (each is a hypothesis to check, not a task list):
- **How people fight.** Do guards just repeat one swing? Do they use their weapon's reach (spears keep you off),
  block, step back, flank with a partner, flee when badly hurt, call for help, surrender, pick up a dropped weapon,
  try to disarm or hold you rather than kill when that fits who they are?
- **How it feels to fight.** Wind-up and telegraph so a blow can be read and answered; clear hit feedback; guard and
  parry timing; stepping back or aside; tiring (stamina) so fights aren't button mashing.
- **Weapons that feel different.** Reach, speed, two hands, cut against thrust against blunt; a spear, a knife and a
  club should each play differently, from their numbers in `gear.json`.
- **Armour.** Weight that slows you, gaps in coverage, wear.
- **Equipment on screen.** Seeing what you and others have on, putting things on and taking them off easily
  (drag to a slot), how long it takes, comparing two weapons.
- **Ranged.** Bows, slings and thrown things: ammunition, range, line of sight (`paths.line_of_sight`).
- **Ending a fight without killing.** Knocking out, disarming, pinning someone who's down. This must agree with
  D-65's restraint law: only someone down, asleep, blindfolded, already bound or willing can be tied or held.

## Fit with Claude's building blocks (D-65)

Effects can now change things and people, and combat must honour what they leave (read `backend/effects.py`; don't
edit it):
- `damage` removes qualities from a thing (`flags`) and records them in `obj["damage"]["lost_flags"]`; `repair` gives
  them back; `destroy` sets `condition == "destroyed"`. A blunted knife (no `sharp_edge`) shouldn't cut like a sharp
  one, a holed shield or a smashed spear shouldn't work at all, and a mended one should work again. Gear should read
  the thing as it is now.
- People have `states` with `limits` (`effects.limited(person, "hands")`, `"move"`, `"see"`). Someone with bound
  hands can't swing or block, someone who can't move can't step in, and someone who can't see fights blind. Check
  that combat respects these, for the stranger and for everyone else.
- Things can be `hidden` (`effects.unseen_by`) or shut away (`effects.shut_in`): a hidden weapon isn't one a guard
  can see you carrying.

## Files

Yours: `backend/combat.py`, `backend/gear.py`, `data/content/gear.json`, `data/content/armourer_notes.json`,
`scripts/fight_view.gd`, `scripts/painted_actor.gd` (fighting animation), `scripts/player_input.gd` (fighting keys),
the pack and gear panel in `scripts/game_ui.gd`, `backend/tests/test_combat.py`, `backend/tests/test_gear.py` and any
new combat or gear tests, `evals/run_gear_evals.py` and any new combat evals, `tools/smoke_fight.gd`,
`tools/smoke_gear.gd`, `tools/profile_combat.gd`.

Claude's (it is changing these now): `backend/effects.py`, `backend/crafting.py` (small changes inside `_harm`,
`_blow`, `_equip` and `_treat` are fine), `backend/judge_view.py`, `backend/briefing.py`, `backend/perception.py`,
`backend/paths.py`, `backend/clock.py`, `backend/npc_sim.py`, `backend/heat.py`, `apply_step` in
`backend/consequences.py`, `backend/ai/judge.py`, every `backend/prompts/judge_v*.txt` and `person_v*.txt`,
`backend/tests/test_deeds.py`, `evals/run_deeds_live.py`, `scripts/world_view.gd`, `scripts/ui/inspect_card.gd`.
If you must touch one of these, keep the change small and self-contained and say so in the commit message.

Don't write a new judge or person prompt version. If the judge or people's own calls need new guidance for fights,
write the lines you propose in `docs/CODEX_TO_CLAUDE.md` with the reason and evidence; Claude folds them into its
next prompt version and A/B tests them.

## The rules that don't bend

- Models propose; only the backend reducer changes the world. Godot shows it frame by frame; the server decides
  every blow (where it lands, what it does).
- No dice (V11): the same situation always has the same outcome. Code owns every number (`gear.json`).
- No fixed recipes or command phrases. People fight from their own motives and nature.
- Keep it fast: 60 fps in a fight. A slowdown once came from comparing pictures as text (D-51); profile with
  `tools/profile_combat.gd`.
- Secrets: API keys live only in `backend/.env`; never print them. Never commit `.env`, any sqlite file,
  `data/assets`, `addons/ziva_agent` or `evals/results`. Don't touch `C:\Users\Burry\.mcp.json`.
- Development art (a new held or worn view, an animation sheet) you make yourself, not through the paid image API.
  Runtime art in the game still uses the API. Live runs during development use `IMAGES=off`.

## Checking your work

- Every commit: `./tools/check.ps1` green. Before handing over: `$env:CHECK_PORT=8768; ./tools/check.ps1 -Full`.
  Use port 8768 so you never collide with Claude's checks (8766) or the user's game (8765, 8767).
- Live, with the real models: the gear evals, and a combat eval of your own (a few scripted fights per problem you
  fixed, each reporting what happened), results in `evals/results/` (not committed).
- Goldens (`backend/tests/golden`): re-record only where the difference is your new fields, and say so.

## Records

- `GDD.md`: update §6.8 (and anything else whose behaviour changes) and add your decision rows as **D-66** onward,
  newest first, above D-65. Claude's D-65 row will keep growing; don't edit it.
- `docs/game_logic_map.html` and `docs/walkthrough.html`: per `AGENTS.md`, edit the source when combat or gear
  changes how the game works, and say so in your commit message so Claude republishes them.
- Finish with `docs/COMBAT_REVIEW.md` updated: the grade after, what you changed, what's left, and any question
  that's truly the user's to decide (don't stop to ask them; note it and carry on with the rest).

## Handing over

Commit on `codex/combat-gear` in steps, each with a green check. When you're done, merge
`codex/player-run-flow-fixes` into your branch, resolve any conflicts on your side, run the full check again,
and stop. Claude and the user will merge it.
