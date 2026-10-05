# Combat and equipment review — 5 October 2026

Worktree: `time-travel-combat`, branch `codex/combat-gear`, starting at `1359755` (includes `81f2d63`).
Claude's checkout and the player's saves are not edited. The source SQLite connection was read-only; a backup
and developer clone (`5c32c04fc50e4feaab62661313b37484`) live only in this worktree. Probes use port 8768.

## Before: combat 43/100; equipment 48/100

These are engineering review grades, not percentages of tests passing. The same rubric will be used after:

| Combat | Before | Equipment | Before |
|---|---:|---|---:|
| Input and pacing /30 | 10 | Classification and handling /25 | 12 |
| Animation and readable feedback /25 | 8 | Current physical condition /25 | 10 |
| Meaningful tactics and agency /20 | 8 | Attachment and presentation /30 | 12 |
| Consistent physical rules /15 | 10 | Equipment usability /20 | 14 |
| Performance /10 | 7 | **Total /100** | **48** |
| **Total /100** | **43** | | |

### Problems in priority order

1. **Controls wait and recovery is misleading.** `fight_view.strike` starts animation after HTTP, waits behind
   the entire movement flush, and builds its version before waiting. Combat clocks flush every 500 ms. The rig
   recovers for a fixed 250 ms plus a 150 ms strike, while the table locks some weapons for another 1200 ms.
   Early input is discarded. A sword takes 700 + 800 ms and a sledge 1300 + 1200 ms before network/batching.
2. **The weapon leaves the hand.** `painted_actor._pose_fighting` offsets the weapon for thrusts without moving
   the wrist. Every texture gets the same guessed grip; a supporting arm rotates independently. Saved
   `gear_rig_attack.png` visibly shows the gap in profile, as well as rigid arm motion and awkward front thrusts.
3. **NPC equipment is absent from the rig.** Only `_sync_player_gear` calls `set_gear`. An NPC's real weapon
   therefore affects the backend but is not attached and shown by this equipment renderer.
4. **New weapons can silently become weak generic equipment.** In player journey
   `f13b366430354f19b3cb881b2c00a9b7`, event 59 makes a 7.9 kg, 0.8 m flanged mace from oak, iron plates and nails.
   The proposed mace exceeds the class's mass limit; no heavy blunt kin is tried. Its record becomes `none` and
   seven recorded strikes use `improvised`, damage 24, rather than a heavy blunt weapon. The player misses Kade,
   hits Elin and is eventually subdued. The journal calls the invention "something swung".
5. **State and action exploits.** In-memory probes show bound hands can start a strike; throwing during a future
   `ready_at` succeeds; a targeted fist facing south hits Hessa to the north (health 80); a knife whose damage
   removes `sharp_edge` still pierces for 35. Destroyed items are not consistently excluded by gear readers.
6. **Opponents close and repeat.** The controller runs into reach, stands during wind-up, then repeats the same
   blow. NPC shields block automatically while idle, without a directional guard state. It does not maintain
   polearm spacing, avoid partners' positions, or react tactically to visible wind-ups.
7. **No obstruction check for missiles.** Existing ammunition and recovery are useful, but shots can cross a
   building because launch and impact do not check the shared line-of-sight rule.

### What already works

Backend ownership of hits; deterministic chronology and replay; physical armour penetration; bleeding and
remedies; held-object identity; practice fights and surrender; two-hand inventory occupancy; image caching.
The 37 existing combat, gear and equip tests pass. They do not cover the exploits above or grip geometry.

## After

Combat **82/100**; equipment **85/100**, using the original rubric:

| Combat | After | Equipment | After |
|---|---:|---|---:|
| Input and pacing /30 | 27 | Classification and handling /25 | 23 |
| Animation and readable feedback /25 | 18 | Current physical condition /25 | 23 |
| Meaningful tactics and agency /20 | 15 | Attachment and presentation /30 | 23 |
| Consistent physical rules /15 | 14 | Equipment usability /20 | 16 |
| Performance /10 | 8 | **Total /100** | **85** |
| **Total /100** | **82** | | |

These are technical review grades. Player judgement of the feel still matters; they are not a claim of finished,
polished combat or a 100% live-model success rate.

Implemented: input-frame anticipation and bounded ordered commands; 100 ms active clock; independent hand
recovery and buffers; shorter shared timings; articulated grips and supporting arms; visible NPC kit;
backend profiles/descriptions; heavy blunt handling; current damage/repairs/body limits; directional contact,
projectile obstruction, parries, spacing and individual reconsideration.

Verification evidence:

- Expanded regressions cover recovery-skipping throws, bound hands, backwards targets, heavy inventions,
  damaged/repaired gear and damage at contact, both hands, directional parries, buildings, concealed equipment,
  model-selected jobs and deterministic clock partitioning.
- Native attachment smoke: 53,664 attack/view samples across eight traveler facings, all ten village paintings
  and a fallback character, both primary hands and two-handed support; grip errors below 0.1 px in the tested
  geometry. Independent hands, accepted anticipation and rejected return are checked. Response smoke adds
  250 ms delayed replies, dispatch-time versions, pre-contact recovery, stale/out-of-order state rejection and buffer clearing.
- Final merged build's rendered 90-second cached-art soak (`data/combat-profile-handoff.log`): median 13.6–13.8 ms,
  window p95 15.8–18.5 ms (roughly 72–74 rendered frames/s); zero orphans. Nodes settled at 2,400–2,402, transient
  peak 2,404; memory 118.9–119.9 MB. Immediate anticipation CPU work peaked at 2.215 ms. One frame reached 103.4 ms;
  the typical frame-rate target is met, with occasional stalls rather than a constant-60-fps guarantee.
  The prior merged soak had p95 15.8–16.5 ms and maximum 30.1 ms. Godot still reports a texture RID during shutdown, also seen before;
  no continuing node/orphan growth occurred during the run. Shutdown resource cleanup remains a follow-up.
  The fixture keeps three opponents and high-health sparring alive; individual motives are held constant.
- Baseline rendered 20-second run: p95 16.6–18.2 ms, stable nodes/orphans, but only 500 ms state updates and a
  fight that did not stay active. It is not a like-for-like performance comparison. Early new-clock soaks
  exposed repeated font/label creation; caching/reuse and off-thread JSON decoding fixed that churn.
- Live gear suite: **15/18**. Combat judge/person scenarios verify physical refusals and legal individual
  choices: **5/5** after merging Claude's `judge_v25` (`combat_20261005_121801.json`). Saved reports remain ignored.
  The legal-choice score does not establish convincing dialogue or correct narration.
  See `CODEX_TO_CLAUDE.md` for the three gear failures and prompt suggestions.
- Final `CHECK_PORT=8768 tools/check.ps1 -Full`: **623 backend tests**, **70 scripts compile**, and **20/20 Godot
  smoke tests**, including combat, gear, crafting, conversations, responsiveness and training. The full check
  was repeated after merging Claude's latest committed branch (`44f17bf`) into this branch and after the
  trap integration. The commit hook repeats fast checks; the handoff is committed only on `codex/combat-gear`.
  No golden files were re-recorded; defaults/expired cooldowns are normalized, and the changed arrest replay
  explicitly asserts its new hit, health and spacing while retaining the original unrelated fields.

Remaining: procedural cutout seams and unusual art/grip conventions need visual polish; front/back strikes have
less visual depth than side strikes. NPC tactics are a deterministic first pass, with motives still dependent on
individual model calls. No new stamina or dodge mechanics. Model narration can disagree with validated weakened
gear; prompt changes and live A/B work belong with Claude. The demo should be played again for subjective feel.

## Decisions for this pass

Keep movement-based evasion, existing keys, and individual model decisions. Defer stamina, a dodge key,
automatic loot selection and a broader armour-weight redesign. Motion families are presentation tools for
arbitrary objects, not a list of allowed inventions. No paid development image generation or new mind prompts.

## Accepted main integration — 5 October 2026

The user accepted this pass and requested the combined demo on the existing server. Main contains the combat
handoff plus a preserved snapshot of Claude's 32 modified files and four new quest source files. Claude's
original `claude/quests` checkout is unchanged. Its quest decision references are D-69 here, avoiding the combat
D-67 numbering collision. The existing judge_v26/person_v7 files come from Claude. Seed 15 requires a fresh
journey; both original databases and the last-run pointer were backed up before restarting the shared service.

Final combined `CHECK_PORT=8768 tools/check.ps1 -Full` passed: **638 backend tests**, **70 scripts compile**,
**20/20 rendered smokes**, including training. Reaction checks cover private quest context once, concealed gear,
and both decide/told reactions. Conversation checks explicitly verify the new greeting and subsequent player
reply; closing before a deferred greeting cancels it and permits reading a held book. A cold response check
initially exceeded its old two-second wait, then passed on rerun; its bounded completion wait now covers both
requests' existing HTTP budgets, retaining the same input-frame anticipation and ordering assertions.

The combat/equipment grades remain **82/100** and **85/100** under the rubric above. This integration did not
repeat paid live evaluations or the 90-second combat profile. Their recorded limits still apply.
