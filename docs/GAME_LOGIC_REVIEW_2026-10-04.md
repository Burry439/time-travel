# Game logic review: The City Beyond

**Reviewed 4 October 2026. Scope: the current working copy, including uncommitted NPC, secret, story and judge changes.**

The game has a strong foundation for an invention-driven RPG. Persistent objects, personal NPC knowledge, social entry routes and replayable consequences belong together. The main weakness is consistency: several systems currently award knowledge, reputation or successful outcomes that the actual sequence of events does not justify. I would keep the central design and repair those rules before adding more content.

This is a review of implemented logic and design, not a rating of the art or a substitute for a human playtest. I read the working GDD and traced the relevant Python, Godot, content and evaluation paths. I ran the existing backend suite: **460 passed in 62.94 seconds**, with one dependency deprecation warning. I also ran isolated, in-memory reproductions of the findings below. No gameplay code, content, design decisions or existing journeys were changed by this review.

The latest saved crafting evaluation, `evals/results/craft_20261004_122835.json`, reports **108/108 passing**, using `judge_v18`, with p50 3.19 seconds and p95 6.46 seconds. That is useful evidence for the tested prompts. It does not establish that the reducer rejects every invalid proposal or that players can discover solutions unaided. I did not make new paid model calls or conduct a graphical playthrough. The local training feedback table has zero entries; that does not prove nobody has played, but it provides no evidence of the five-unbriefed-player acceptance gate in GDD section 10.3.

**What is working well and should stay**

| Part | Why it is good | What to preserve |
| --- | --- | --- |
| The core intention loop | The player can describe an unauthored object, create a persistent entity, then carry, show, give or build with it. This gives knowledge a practical role. | Free-form descriptions and general physical consequences; do not substitute mandatory recipes or command phrases. |
| Object identity and provenance | Created objects have engine-assigned IDs, consumed components, ownership, possession, creation history and asset references. | One object record for authored and invented things. Ownership must remain distinct from possession. |
| Backend authority and event history | Commands validate requests, save changes, support idempotent retries and replay patches without calling models. This is a substantial technical strength. | The command/reducer boundary, checkpoints, golden journeys and replay verification. |
| Personal NPC calls | The current voice path gives each person their own sheet, knowledge and secrets; others receive public identities and spoken lines. | Individual minds and authored motives. Reactions should remain their own decisions. |
| Multiple ways to enter | Sponsorship, business, practical value, individual guards' motives and an unbarred physical gate create different strategies. Permission does not win until the player actually enters. | Evidence-based permission and physical movement as separate facts. Ordinary helpful work should remain a valid route. |
| Witnesses and travelling news | Code handles sight, memory sources, errands and reports; good news can travel as well as crimes. | Knowledge arriving through observation or communication, with the source recorded. |
| Material consequences and gear | Water conservation, burning/cooling, equipment, armour, wounds, treatment, arrest and rewind make actions matter beyond dialogue. | General laws and shared damage rules. These systems need consistency fixes, not wholesale removal. |
| Training and the device | Short, optional lessons are a better place for explicit guidance than the main sandbox. Advanced-level coaching avoids the written intended answers. | Teach controls and reasoning; leave room to solve problems differently. |

Useful source anchors: [object creation](../backend/consequences.py#L78), [event replay](../backend/store.py#L215), [commands](../backend/commands.py), [individual NPC calls](../backend/ai/voice.py#L289), [admission grounds](../backend/gatekeeping.py#L62), and [device context](../backend/device.py#L174). Line anchors identify the reviewed version and may move with later edits.

**The most serious problems, and the replacements I recommend**

**1. Repeated proof still farms trust. High priority; directly reproduced.**

`backend/reputation.py:175` credits evidence by event ID. A repeated demonstration creates a new event ID, so the same proof earns full trust, suspicion reduction and respect again. `backend/talk.py:50` also expands the available goodwill budget using the number of evidence events.

In an isolated state, six repetitions of the same ordinary demonstration changed Roderic from **trust 0.15 / suspicion 0.68** to **trust 1.0 / suspicion 0.0**, with respect 0.9. The admission-grounds check then returned true. This does not guarantee that the model will admit the player, but it gives repeated proof unlimited influence over the facts the model reads. The GDD explicitly says repetition should not stack.

Replace event-only credit with an **evidence ledger**. Keep the event ID for provenance, but also identify what was proved: object identity, tested capability, relevant conditions, recipient or beneficiary, and original source. Seeing the same thing again may improve certainty or ease first-time fear, but should have sharply limited reputation credit. A new application, a more demanding test or a new useful service may count as new evidence. Rumours about the same underlying deed should inherit its evidence identity.

Keep trust, respect and fear distinct. A clever tool should prove competence; usefulness and honest conduct should determine what further trust it earns. Otherwise every guard's different motive eventually collapses into the same repeat-until-friendly strategy.

**2. Story outcomes give NPCs knowledge before it reaches them. High priority; directly reproduced.**

`backend/stories.py:296` applies story effects globally. The `told_roderic` outcome in `data/content/stories.json:49` reduces Tomas's trust as soon as the captain hears Tomas's secret. `stories.how_things_stand` then supplies that outcome to Tomas's own conversation context.

I placed Tomas and Roderic about **66 cells apart**, told only Roderic, and advanced the story. Tomas's trust fell from **0.3 to 0.0**, with **no new memory** reaching him. His context nevertheless said the stranger had told Roderic and that Tomas would not forgive it. Separate model calls cannot preserve personal knowledge when their input already contains an unseen global outcome.

Replace global social effects with **knowledge-dependent consequences**. The captain may change his view immediately. Tomas's reaction should wait until he witnesses the disclosure, is told, overhears it or sees some consequence that lets him infer it. Keep a world fact that the disclosure happened, then deliver sourced information through the existing perception and errand systems. Build each NPC's story context from their own known facts. The same requirement applies to gifts, debt forgiveness and other story rewards affecting distant people.

**3. Stories close too early, and some completion checks confuse an object with a solution. High priority; directly reproduced.**

The story engine picks the first matching outcome and permanently closes that story. For the gate beam, knowing Tomas's secret and installing the beam produces `kept_quiet`. If the player tells Roderic the secret afterwards, Roderic learns it, but the story remains `kept_quiet` and the betrayal penalty is never applied. In the reproduction, Tomas's trust stayed **0.55 before and after the later disclosure**.

The fog story has another problem. Its completion check accepts a gift carrying either `indicates_direction` or `magnetized`. I handed the watch an **untested magnetized needle** with no demonstrated navigation capability. The story immediately concluded that the watch had a way to find north in fog, despite **zero demonstration memories**. Magnetism alone is not a usable navigation instrument, and possession alone is not proof that it works.

Replace permanent mutually exclusive story endings with **ongoing world predicates and recorded milestones**. A beam can be repaired, then a confidence can be betrayed later. Both events should remain possible and consequential. A practical need should be fulfilled by observed function under relevant conditions, not by a convenient flag or name. Keep authored needs and conflicts: they are good content. Use the Stories journal to summarize what happened rather than make it the authority that decides what everyone now knows.

For irreversible outcomes, make the irreversibility a real fact: someone died, an object was destroyed, a debt was actually released. "Has not disclosed a secret yet" is not an irreversible fact.

**4. Multi-step attempts discard important consequences and cannot be interrupted between steps as designed. High priority; directly reproduced and traced.**

`backend/consequences.py:521` validates and applies steps on a draft. Its summary keeps only the last harm, demonstration, gift and several other effect types. `backend/perception.py:16` then constructs witnesses from that summary, and `backend/routes_craft.py:262` perceives the completed attempt before advancing people once by the total effort.

I submitted an attempt that punched Tomas and then Hessa. **Both ended at 80 health**, but the perceived violence named **only Hessa**. Tomas's attack had a physical effect without its own corresponding witness projection. Similar information loss can occur when a line gives to two people or demonstrates two things. The first property claim also represents a theft involving multiple objects or owners too narrowly.

Replace the aggregate summary as the source of consequences with **one structured result per step**. Each result needs its own actor, target, object IDs, location, time, observations and property claims. Revalidate, advance time, commit and perceive before proceeding. A reaction or interrupted task must be able to stop the remaining steps while preserving completed work. A player-facing summary can still be assembled afterwards.

For long work, use interruptible progress in the planned time segments. A several-minute task should not become fully completed before the guards, the fire, bleeding or material access have had a chance to change.

**5. Combat changes with clock batching, and model waits disable the player's response. High priority; directly reproduced for ordering, statically traced for input.**

`backend/combat.py:377` resolves due player swings before checking due NPC swings. It does not merge both sides into chronological order. In a controlled setup, the NPC's blow was due at 100 ms and the player's killing blow at 200 ms. With one 300 ms update, the player finished at **100 health**; with updates of 100 ms then 200 ms, the player finished at **52.5 health**. The NPC died in both cases. The network/clock batch size changed who got to hit first.

The same loop processes at most one existing NPC swing per attacker in that call, which makes bulk time advancement unsuitable for resolving an entire long action. Separately, `scripts/main.gd:396` continues the fight clock while a request or blocking panel is active, but the movement path returns at line 403. `scripts/actions.gd:77` waits up to 150 seconds for an action response. A slow conversation can therefore leave the player exposed while movement is disabled.

Replace combat's player-first processing with a **shared event timeline**, ordered by landing time, with an explicit rule for exact ties. Process every due event through the advanced interval. A swing should keep the committed weapon/action profile or be explicitly cancelled when it changes. Use the same timing and hit-resolution primitives for described attacks and hand-button attacks.

Keep real-time movement in Godot. While an AI request is pending, allow the player to move and defend, then revalidate the proposal against the latest world. If a specific physical task occupies the player, that restriction should come from the task and its declared effort, not the provider's response time.

**6. Some advertised hard physical laws are still only prompt instructions. High priority for the game's integrity; boundary gaps reproduced with fabricated proposals.**

The code guards useful things, including available references, consumed mass, water, heat and gear classification. It does not enforce the full contract in GDD section 6.2.

I supplied a proposal for **magnetized bronze** using a real magnetic source. The validator stripped `ferromagnetic` but retained `magnetized` and returned success (`backend/crafting.py:94`). I also supplied a proposal for a **1 kg iron pan with 100,000 L capacity**, no tools and no forge: it returned success with that capacity unchanged (`crafting.py:307`). These are tests of the validator boundary, not claims that the current live model normally produces those answers.

There is also no implemented precedent-conflict check corresponding to GDD V8. `backend/judge_view.py:188` supplies the last ten rulings to the model, and keys are stored, but the validator does not compare a proposed ruling with a canonical or saved ruling. The documented specialist-skill/facility requirement is not a general check in the make path either.

Replace prompt-only laws with **explicit physical invariants and operation requirements**. Reject incompatible active properties. Validate meaningful physical bounds together, rather than just making every number positive. Require the necessary facility and skilled help for relevant operations, while preserving the design's deliberate allowance for using others' property with consequences. Store normalized precedents with the conditions that matter and retrieve them by method; conflicts should get a bounded reconsideration or an honest unresolved result.

Do not silently turn a major invalid proposal into a smaller or different successful object while keeping the original success narration. Reconcile the reason and displayed properties with the validated result. Extend general laws as player attempts reveal gaps; do not add a per-item recipe list.

**7. A named audience bypasses sight and distance. High priority for knowledge integrity; validator/perception gap directly reproduced.**

`backend/crafting.py:995` retains an audience ID if it is a living person. `backend/perception.py:252` treats an explicitly involved audience member as close and clearly informed without requiring a sight check.

A demonstration at the south road gave Roderic a **clear, firsthand memory from about 55 cells away** when his ID was placed in the audience list. A model normally receives nearby people, so this reproduction establishes an enforcement hole rather than a guaranteed natural-language exploit. Nearby people behind buildings are subject to the same bypass.

Replace "named means witnessed" with **named means intended audience**. The engine must determine whether each audience member actually perceived the demonstration. Only physical participation, valid sight or a legitimate communication channel should produce firsthand evidence. Apply a shared visibility projection to the device too: its current `people_in_sight` and `things_in_sight` lists filter by radius, not line of sight.

**8. Theft settlement uses item names and spreads knowledge globally. Medium priority; directly reproduced.**

`backend/reputation.py:118` settles theft after a hand-over by matching the object's name. `settle` then marks matching memories settled for every NPC, regardless of who observed or heard about the return.

In a controlled state, returning a different object named **"coil of rope"** to Hessa cleared the memory of stealing Tomas's rope. Tomas's actual rope was not returned. Even a legitimate return should not immediately inform a distant guard who has not heard it happened.

Replace names with **stable object and incident IDs**, retaining the original owner and the actual restitution event. Settle the underlying incident when it is put right; update each NPC's belief when they learn of the restitution. Human-readable names belong in the display, not in identity checks.

**What could be improved after those repairs**

**Make novel objects useful in more than a reputation calculation.** The bounded operation vocabulary is appropriate for a demo, and combining or reusing an object already works. However, `demonstrate` chiefly updates capability observations and reputation; it does not itself apply arbitrary physical changes. Extend a small set of reusable effects where player attempts justify them: moving liquid, supporting a load, fastening objects, directing light or sound, or improving a task's effort and safety. The judge can compose these effects from properties; the backend should verify them. This makes a new tool valuable in a second problem instead of only impressive in a second conversation.

**Allow negotiated agreements beyond authored task templates.** `backend/conversation.py:242` builds task offers from NPC cards. Trade, lending and several story decisions add flexibility, but arbitrary task-for-reward agreements are still narrower than the pitch suggests. Add validated contract terms: a result the NPC can observe, the reward they actually control, the completion evidence and permitted assistance. An NPC may propose or accept these terms through their own model call; code creates and fulfils the contract. Authored offers should be examples of useful work, not the complete set of possible bargains.

**Keep the mundane route, but make knowledge create distinct opportunities.** Fetching water and earning sponsorship is a good accessible strategy. Do not require a compulsory invention to finish. Give inventions practical effects that open different relationships or opportunities: a repeatable heading for the patrol, easier safe lifting for the carpenter, less wasted fuel for the smith. Those needs should accept multiple methods. Success should depend on what the method actually changes, not the object being called a compass or pulley.

**Make promises and completion legible.** Present "offered", "agreed", "work completed", "reward carried out" and "permission granted" as different states. Keep the existing visible errands. A character saying they will speak for the player should not look equivalent to the captain having heard them. For every important result, let the journal answer: what changed, who knows, what they saw, and what is still outstanding.

**Use precise feedback.** `backend/views.py:55` labels the first player-created object an invention that nobody in the world had before. Gathered pieces also use player-created records, and familiar crafted objects are not necessarily historically novel. Celebrate the actual achievement: gathered, made, repaired, demonstrated, put to use, or taught to someone. Reserve novelty claims for evidence against the knowledge baseline. Distinguish an invalid physical idea from a missing simulation capability and from an unavailable service.

**Bound response time without destroying NPC identity.** Keep the private per-person contexts. Reduce unnecessary bystander calls, keep context relevant and impose actual per-role deadlines. The shared client currently uses a 180-second provider timeout (`backend/ai/config.py:98`), while the GDD describes much shorter interaction deadlines. A changed model alone will not solve long waits caused by work queues, repeated calls or client input locks. Measure end-to-end interaction time, not just one model's latency.

The saved 4 October persona evaluation identified 43 of 60 replies by speaker and recorded 16 shared openings. That is a useful sign that voices still have room to improve, but its label is `person_v1`, while the current working prompt is `person_v2`; it is not a current-version failure rate. Evaluate voice identity together with remembering, appropriate refusal, relevant questions and actions that follow spoken commitments.

**Use training to teach transfer.** Basic lessons may give exact example words. Advanced lessons should test a goal with several acceptable methods, then make the player apply the idea in an unfamiliar setup. Measure whether someone can later act in the village without copying a suggested sentence. More training levels do not themselves prove that free-form understanding works.

**Freeze content long enough to test the actual demo.** The critical uncertainty is whether an unbriefed player can notice a problem, form a plan, recover from a failure and understand NPC reactions. The GDD's five-player gate is the right next validation. Keep screenshots and raw waiting time alongside saved events; scripted successful routes cannot reveal every confusing choice or unsupported attempt.

**Recommended implementation order**

| Order | Work | What should pass before moving on |
| --- | --- | --- |
| 1 | Evidence identity, witness eligibility, NPC knowledge and incident identity | Repeating a proof cannot max trust; a distant NPC cannot see a named demonstration; neither a betrayal nor restitution reaches an uninformed NPC instantly; two same-named objects remain distinct. |
| 2 | Step-specific consequences and chronological time/combat | Every affected victim and owner gets the correct projection; reactions can interrupt later work; splitting the same elapsed interval into different clock batches gives the same result. |
| 3 | Active-property constraints, skill/facility requirements and precedent enforcement | Invalid model proposals cannot create magnetized bronze or impossible capacities; familiar methods get consistent outcomes; displayed narration agrees with committed facts. |
| 4 | Ongoing needs and reversible social developments | Repairing the beam does not immunize later betrayal; an untested needle cannot fulfil navigation; NPCs react only to evidence they hold. |
| 5 | Input during model waits, deadlines, practical reuse and flexible contracts | Latency cannot arbitrarily prevent defence; a held-out invention solves a second problem; a player-negotiated valid agreement executes without a scripted route. |
| 6 | Frozen-content human playtest | Apply GDD section 10.3: five unbriefed players, at least three entrants, at least three meaningful knowledge demonstrations, and at least two different knowledge applications. |

The regression suite should add invariant and sequence checks, especially repeated evidence, distant knowledge, exact property restitution, alternative completion order and clock partitioning. Keep held-out inventions and varied phrasing out of prompt tuning. Tests that force the expected model decision are useful for reducers but cannot alone grade whether an actual NPC would understand the player.

When implementing these recommendations, update the corresponding CURRENT or EXPERIMENT GDD sections and record significant decisions. Reconcile the obsolete claims too: the scope still excludes combat/healing although those are implemented, some old NPC sections describe superseded authority and model pipelines, and V4/V6/V8 currently promise stronger enforcement than exists. These contradictions matter because the GDD is supposed to be the source of truth.

**Grade**

| Area | Current assessment |
| --- | --- |
| Core invention concept | 9/10 |
| Invention and reuse implementation | 7.5/10 |
| Persistence and command architecture | 9/10 |
| NPC knowledge and social consequences | 6/10 |
| Physical consistency and model-output enforcement | 5.5/10 |
| Time and combat consistency | 4.5/10 |
| Progression and feedback | 6.5/10 |

These are judgment scores, not percentages of tests passed. The overall mark puts the most weight on the consistency of the central loop. Strong code organization and many passing tests cannot compensate fully for a player discovering that repeated proof earns unlimited trust, someone knows an unseen betrayal, or a fight changes with clock batching.

**Overall game-logic grade: 6.5/10. A promising, capable prototype with a distinctive core, but important consistency rules need repair before I would call the logic ready for the demo.**
