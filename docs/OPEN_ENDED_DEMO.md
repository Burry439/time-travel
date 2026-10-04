# Open-ended demo repair — D-62

Implemented on `codex/open-ended-demo`. The pre-change workspace, including the existing unfinished work, is preserved at `codex/demo-baseline` / `994def4`. `main` was not changed. The launcher uses its own database, `data/open-ended-demo.sqlite3`; the original `data/demo.sqlite3` is preserved.

The AI judge reasons about the player's method and actual resources. New inventions do not require authored recipes. Each predefined NPC interprets its own evidence and chooses its response. Models propose; the backend commits the world.

## Changes

| Problem | Implemented replacement |
| --- | --- |
| Repeated demonstrations could farm opinion changes, especially after memories were pruned | Durable proof identities and per-person opinion budgets. Paraphrases, repeated proofs and circular news do not create new evidence. |
| Story outcomes changed absent people's minds and stopped later consequences | Ongoing factual milestones. Personal knowledge and interpretations stay with actual witnesses and recipients. |
| NPC motives were overridden by universal trust, crime and fear gates | Individual model judgments with resource, authority and physical checks. Convenient authored moves remain examples; free-form physical intentions and negotiated tasks extend them. |
| A functional-looking gift or claim could certify real success | Expected properties, observed tests, objective evidence and NPC satisfaction are separate. A person can be deceived without rewriting physics. |
| A several-step action lost earlier victims or effects | Each completed step advances world time, revalidates resources, records its witnesses and persists its consequences. Later failures retain completed work. |
| Combat could discard an earlier NPC impact or use a changed weapon | Chronological impacts and recovery, bound weapon identity, and interruption of unfinished work. Consensual practice remains practice. |
| Impossible masses or bronze magnetization could slip through | Backend quantity/material checks and rejected contradictory proposals. Helpers require an actual, available commitment. Causal cases include method, resources and helper availability. |
| Remote named audiences or copied returned goods produced false social facts | Physical perception and exact object/incident identities. Restitution reaches absent people only through news they believe. |
| A pending model request froze movement or overwrote newer state | Escape closes the bar; movement and defense continue. The result is revalidated against the latest world, including death, and client movement is reconciled. |
| New shapes could lose their properties or keep an old picture | Extensible attributes survive creation, gathering and transformation. Changed shapes receive new sprite IDs; image prompts, cache signatures and Godot textures reflect the new properties. |

The shared person contract covers speech, silent reactions, news and day plans. NPC physical work uses the same judge and reducer with that person's resources and abilities. Negotiated rewards are validated and paid once. Existing authored examples remain available without restricting new tasks.

## Verification on 4 October 2026

- `tools/check.ps1 -Full`: 484 backend tests, 65 GDScripts compiling, reference checks, Python/GDScript lint, and all 18 Godot smoke tests. The added smoke coverage checks movement during a pending intention and replacement/restoration of a changed object's picture.
- Golden API journeys were deliberately updated for seed 14, durable evidence, chronological work/combat and ongoing consequences. Ordinary runs compare those states and independently verify reload equality; they do not call a model.
- [Final held-out model report](../evals/results/open_ended_20261004_142733.json): **14/14 passed** across two runs. It covers carving an unauthored groove, using it again, rejecting absurd capacity and bronze magnetization, rejecting uncommitted help, negotiating a new task and allowing an individual guard decision. Latencies: **2.63–12.45 seconds**, median **4.69 seconds**. The guard chose to refuse in these samples; the test does not require a particular social answer.
- [Two complete live API playthroughs](../evals/results/routes_20261004_172054.txt): Hessa's recommendation and Darin's trade route both reached the city. [Follow-up trade playthrough](../evals/results/routes_20261004_172637.txt) also reached the city after correcting a redundant agreement acknowledgment that had produced misleading dialogue.
- [Live HTTP and art report](../evals/results/demo_http_20261004_143025.json): creation and save/reload passed; the revised branch received an actual transparent 1024×1024 PNG from `gpt-image-2.5-flare` in **9.79 seconds**, which was served by the backend. Visual inspection confirmed the groove and tick marks. The sprite itself is generated save data and is not committed.
- Earlier reports remain available: [5/7](../evals/results/open_ended_20261004_133233.json) exposed an empty evaluation gourd and an offer incorrectly requiring immediate reach; [10/12](../evals/results/open_ended_20261004_135047.json) exposed properties lost by transformation. Those issues were corrected before the final held-out run.

Speech uses a shared twelve-second model budget (D-63: eight seconds cut off a quarter of a group's calls); physical requests use fifteen seconds, including retries and reconsideration. Network and response-processing overhead can add a little wall time. Image generation has its own background budget and does not hold movement or the action response.

## Play and rollback

From the repository root:

```powershell
.\tools\run_demo.ps1
```

Put the key in `backend/.env` under `OPENAI_API_KEY`. The launcher checks real credentials, starts a hidden backend on port 8767 and opens Godot. Start a new journey for this branch. Use `-BackendOnly`, `-Port`, or `-GodotPath` as needed. `-Stub` verifies the pipeline without demonstrating real model intelligence.

To repeat live evaluation without changing saves:

```powershell
backend\.venv\Scripts\python.exe evals\run_open_ended_live.py --runs 2
backend\.venv\Scripts\python.exe evals\run_routes_live.py sponsor business
```

The held-out checks use in-memory worlds; route playthroughs use temporary databases and skip paintings. `evals/run_demo_http.py` checks the real launcher backend, creates one developer journey in its demo database and pays for one painting.

To go back, stop this launcher's backend after checking the PID in `data/demo-8767.pid`, then:

```powershell
git switch codex/demo-baseline
```

Restart with the baseline's launcher. Stop and restart backends when switching code branches or changing `.env`; running Python processes retain loaded code and credentials.

## Remaining demo gate

This is a verified demo candidate. M6's unbriefed human playtests have not been performed here. Model judgments can still vary, and extensible attributes represent facts rather than a general mechanical simulation of every invention. Unsupported effects must remain honest about that limit.

The next test is five new players, without prescribed phrases: let them invent something, test or revise it, pursue their own social approach and try to enter the city. Record confusing refusals, invented resources, false promises, repetitive NPC behavior, waiting time, and whether art matches their committed invention. Passing automated routes alone does not satisfy that human gate.
