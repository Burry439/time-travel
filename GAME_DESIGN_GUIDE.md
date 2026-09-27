# Time Travel RPG Game Design Guide

> **Superseded on 27 September 2026 by [GDD.md](GDD.md).** Kept for reference only; where the two disagree, GDD.md wins.

Version 1.0 · 26 September 2026

This is the working guide for the game. The older, longer GDD is background research, not a checklist or a reason to delay the core experience. The first priority is to prove that a player can change a persistent world through an original idea.

## The game in one paragraph

The player is a traveler from the future who arrives outside a closed city with only their knowledge. The city, its geography, materials, and main characters are authored. The player describes what they intend to do in ordinary language. The game judges the attempt against what exists, lets characters respond from their own knowledge and motives, and preserves the resulting changes. The player can create an object we never designed in advance, see a generated sprite for it, and use that same object in later plans. The immediate goal is to get inside the city by a coherent route; no single invention or conversation is the required answer.

## The player loop

1. Explore with normal movement. Inspect or pick up an object with a quick action.
2. Speak or enter an intention in the player's own words. Optional highlighting helps resolve references, but exact verbs and prewritten recipes are never required.
3. Interpret the attempt as steps and identify the people, objects, tools, and desired result. A longer intention may include a permitted pickup as an ordinary step.
4. Check world facts: reach, possession, ownership or permission, quantities, materials, tools, time, and what each character has seen or heard.
5. Judge uncertain methods and social choices. A well-worded sentence does not guarantee success. The game may succeed, partly succeed, fail for a specific reason, or ask one useful question.
6. Commit only validated changes. Show the outcome, update memories and the journal, and let the player use the new situation for the next idea.

An example: a player describes making a direction finder from a needle, cork, water, and a real magnetizing source. If the method and resources work, the game creates a **new** object with its own ID, components, properties, provenance, location, and sprite. A guard does not automatically believe it is useful; the player may demonstrate it, and the guard responds to what they actually observed. The compass is an example, not a mandatory recipe or pre-authored item.

## Authored world and emergent content

The starting world has stable locations, physical resources, owners, a closed gate, and named characters. The initial cast is Roderic, Bren, Oren, Hessa, Mara, Jory, Tomas, and Darin. Their roles, motives, limits, and starting knowledge are authored. Their dialogue, decisions, memories, relationships, and reactions are produced from play rather than fixed quest scripts.

Player-created content is persistent. An object record stores its ID, name, materials and component IDs, measurable properties, condition, owner, holder, location, creation event, known capabilities, uncertainties, and sprite asset ID. Its image makes it visible; the record lets the simulation and AI reason about it. Models can propose a new property or outcome, but code checks references, conservation, access, and authority before saving it. Unknown capabilities can remain uncertain until tested. Characters know about an object only if they perceive it or receive a claim about it.

After a successful creation, an image model produces a sprite that matches the game's visual style. The world object exists as soon as the result commits; image generation may finish afterward. The sprite is stored under a stable asset ID, loaded into Godot during play, and restored with the save. A usable temporary visual keeps play moving if generation is slow or fails. We do not need to add every possible crafted object to the editor beforehand.

## NPC phantom controllers

Each NPC has a persistent controller state: current goal, activity, personality and motives, relationships, beliefs with sources, inventory, location, attention, and recent decisions. This is game data, not a separate long-running chat session. Jev receives a compact view of that state and answers typed questions such as **Did Hessa notice the demonstration?**, **Does she care?**, **Will she inspect, question, help, refuse, or ignore it?**, and **Which reachable goal should she pursue next?** It can make most routine NPC decisions. [TypeSafe's official Jev documentation](https://docs.typesafe.ai/introduction/quickstart) shows that Jev returns choices, scores, and yes/no probabilities rather than prose.

“Real time” means an NPC reacts promptly to meaningful events and follows an ongoing plan. It does not mean calling a remote model every animation frame. Godot moves and animates NPCs locally. Jev is called when something relevant happens, when an NPC must choose among valid next actions, or on a slower nearby activity beat. Distant NPCs use sparse updates. Several related questions can share one decision request. If Jev is uncertain, the system asks a stronger model or keeps the NPC's current safe behavior. This event-driven schedule is our cost and latency strategy; actual costs and response times must be measured in this game before promising a budget.

Jev selects among context-specific actions; it does not write new dialogue or invent physical facts. When a player-created object creates a truly unfamiliar situation, a language model can propose new candidate intentions for an NPC, Jev can rank valid options, and game code can execute one. The goal is character agency without canned quest branches.

## Technology and model roles

| Component | Job in this game |
| --- | --- |
| Godot 4.7 | Movement, animation, interface, collisions, and rendering authored and runtime-created sprites. |
| Python service and SQLite | Canonical world state, event history, saves, object records, validation, and model routing. Godot's AI MCP addon helps development; it is not the game's runtime judge. |
| Jev | Default low-cost typed decisions for NPC perception, priorities, reactions, and action selection. |
| GPT-6 Luna (`gpt-6-luna`) | Parse player language into a structured attempt and write concise dialogue or feedback. |
| GPT-5.6 Terra (`gpt-5.6-terra`) | Handle occasional ambiguous social situations, NPC candidate plans, and context synthesis that exceed a simple Jev decision. |
| GPT-6 Sol (`gpt-6-sol`) | Judge genuinely novel physical methods, inventions, and difficult multi-step consequences. Use only when simpler checks cannot resolve the attempt. |
| GPT Image 2 (`gpt-image-2`) | Generate and cache sprites for genuinely new player-created objects after their existence is validated. |

These are **API model IDs**, not promises that a ChatGPT subscription supplies runtime API access. OpenAI's [model catalog](https://developers.openai.com/api/docs/models) currently lists GPT-6 Luna and Sol, GPT-5.6 Terra, and GPT Image 2. Model routing is our design choice and must be tested for quality, latency, and cost. Keep provider credentials on the backend. The game should never require all models for every action.

## The first playable proof

Build a small city-gate slice before expanding the world. It passes only when a player can:

1. Describe a plausible object that has no pre-authored item or recipe, make it from real available materials, receive a generated sprite, and see it in the world.
2. Save, reload, pick up, inspect, and use that same object in a second free-form attempt. Its properties and creation history remain consistent.
3. Show or discuss it with a predefined NPC, who notices and reacts according to what that NPC knows and wants; the response is not a fixed dialogue tree.
4. Reach a credible city-entry outcome through a chain of actions and character decisions. A different plausible plan must have room to work; a physically invalid or unsupported attempt must fail honestly without creating an item.

Start with a few active NPC controllers and expand to all eight once the loop is convincing. Keep the map and existing movement work. Replace the current command-verb parser and canned Hessa task as the main interaction path; they are prototypes of persistence and validation, not the intended game design.

## Rules that protect the idea

- A player's words express an attempt, not an automatic world change.
- No mandatory hidden recipe, required object, or fixed dialogue branch solves the city goal.
- AI output is a proposal. Only the validated world reducer creates, moves, transfers, or destroys entities.
- An image does not define physics. Object properties and observed tests do.
- NPC beliefs are personal and sourced; NPCs are not omniscient.
- Failed plans give a concrete reason without revealing a complete solution.
- The first successful demonstration matters more than building a large catalog of systems.
