# Combat handoff to Claude — 5 October 2026

Branch: `codex/combat-gear`, worktree `../time-travel-combat`. User/Claude checkout and its running game were left alone.
Development service/check port: 8768. AI development used `IMAGES=off`. No judge or person prompt version was created.

## Implementation

- Immediate anticipation held before acknowledgement, then contact/recovery on the server timeline; each hand is independent. Commands dispatch with current versions and aim between bounded movement requests. Active clock 100 ms, exploration 500 ms, recovery buffer 180 ms.
- Articulated painted arms, actual primary grip attachment, secondary grip constraints, eight traveler views and separately measured village anchors, NPC gear synchronization and procedural pending/unsuitable art. Texture instance caching includes dimensions, grips and required hands. Native checks sample 53,664 poses, including either primary hand and the fallback character.
- Backend-derived `view.gear` supplies profiles, words, slots and equip time. The saved 7.9 kg mace now resolves to heavy blunt/two-handed gear with its own name.
- Bound hands, inaccessible/destroyed items, lost rigidity/flexibility and damaged shields cannot act. Blunted edges weaken committed blows; repairs restore later use. Facing/reach/LOS checked at contact; projectiles stop at buildings. Directional guard/parry rules and NPC spacing/available approaches are deterministic.
- Significant combat changes request the existing individual reaction call. Its existing fight module receives the current fight and reason; concealed equipment is omitted from its situation. Carry-on preserves combat, and flee/help/stop jobs replace it.
- Combat positioning calls the existing `effects.spring` helper, so fighting people trigger world traps and obey the resulting movement/hand limits. That helper and the fire/time reducers are unchanged from Claude's commit.
- Font caching, health-label reuse and worker-thread JSON decoding remove render-thread churn. No change to `world_view.gd` or `effects.py`.

Shared integration changes: `main.gd` schedules the active clock/movement lane; `net.gd` decodes large replies off-thread;
`views.py` adds derived gear; `routes_gear.py` adds optional facing and treatment preconditions; `routes_minds.py` wires existing
fight context, with no prompt edits; `minds.py` preserves a fighting job on carry-on and offers the general stop-fighting choice.

## Evidence and prompt recommendations

Real gear suite: 15/18 passed (`gear_20261005_111601.json`, ignored `evals/results/`). Failures were club creation
(the judge chose a transform and the evaluator only found a make), strangling an alert Oren (correct refusal;
the old case assumes unaware), and a shove reported unresolved. Don't loosen restraint/awareness rules to force those passes.
Proposed next judge guidance: "For a physical transformation, name the actual retained object or produced pieces;
its gear follows its current shape and material. Narration must agree with the validator's final damage type and outcome."
Evidence: the blunted-knife live case caused weaker blunt damage but narrated piercing.

Real combat calls verified bound described attack refusal, weaker blunted equipment, and individual injured-guard,
injured-smith and fallen-ally decisions. Initial guard calls asked ordinary gate questions during an active fight;
the existing fight module was missing from reconsideration context. The integration now passes it plus the triggering fact. Repeating the three personal calls produced urgent calls for help in all three cases (3/3 legal choices).
Proposed next person guidance: "During a fight, answer the injury, disarmament, fallen ally or surrender that prompted
your reconsideration. Use your own purpose and what you actually perceived; don't start a fresh gate introduction."
A legal move passing an eval is not evidence that the motive/dialogue is convincing; review the saved transcripts.
After merging `44f17bf`, all five combat cases passed again with `judge_v25` (`combat_20261005_121801.json`).
The blunted-knife narration still describes piercing despite the validated weaker blunt hit. The 18-case gear
score above was measured before that merge with `judge_v24`; it was not silently promoted to a full pass.

## Verification and limits

Fast checks, rendered smoke checks, tutorial/combat flows and final upstream integration results are recorded in
`COMBAT_REVIEW.md`. Goldens were not re-recorded. Defaults and expired cooldowns are normalized; the changed
500 ms arrest replay asserts the exact new hit, health and spacing delta while retaining the other original fields.
Final `CHECK_PORT=8768 tools/check.ps1 -Full` passed: 623 backend tests, 70 compiled scripts and all 20 Godot smokes.
Claude's latest committed `codex/player-run-flow-fixes` at `44f17bf` is merged into this branch; its effects,
clock, judge/schema/prompt and world renderer sources remain identical to that upstream revision.

The rendered soak uses an explicitly isolated, high-health sparring fixture with three opponents, cached art,
and already-selected motives held constant; ordinary fighting, injury, treatment and surrender are separate checks.
The final 90-second run holds median frames at 13.6–13.8 ms, window p95 15.8–18.5 ms, nodes at 2,400–2,402 and orphans at zero.
Anticipation takes at most 2.215 ms CPU on the input frame. One frame stalls for 103.4 ms; typical frames meet
the target, but a constant 60 fps is not guaranteed. The existing shutdown texture RID diagnostic remains;
it does not grow during the measured run, and should be followed up separately.
Its measurements do not cover arbitrary new art, huge battles or live model latency. Grip inference assumes the
existing diagonal orientation contract; unusual pictures can still need anatomical/art polish. Movement is the
only evasion control; stamina, a new dodge button and a wider armour-weight redesign remain deferred.

Republish `docs/game_logic_map.html` and `docs/walkthrough.html` to their existing artifact addresses after accepting
the branch. Merge the combat branch only after reviewing the changes; this handoff does not merge into main or your branch.

To play the isolated branch, run `./tools/run_demo.ps1 -Port 8768` from `../time-travel-combat` (add `-Stub` for
local-only play). It uses that worktree's environment and its own `data/open-ended-demo.sqlite3`, leaving the
player's current game and save alone. Development live evaluations used `IMAGES=off`; full stub checks used
deterministic stub sprites, with no paid art calls.
