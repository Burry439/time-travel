# Project guidance

Read [GDD.md](GDD.md) before changing gameplay, content, or AI architecture. It is the single working design and includes the milestone plan (section 11). `GAME_DESIGN_GUIDE.md`, `docs/Time_Travel_RPG_GDD_v0_8.docx`, and the milestone notes in `docs/` are historical reference only.

Protect the core loop: player intention can create persistent, previously unauthored objects and consequences; generated art depicts those objects; predefined NPCs react from their own knowledge and motives. Do not turn the central experience into fixed recipes, command phrases, or scripted quest branches. Models propose; only the backend reducer changes world state. Godot handles per-frame movement and presentation.

Respect the GDD status tags: LOCKED sections change only by recorded decision; CURRENT sections change with evidence; EXPERIMENT sections (notably the AI layer and which model fills each role) are expected to change. When behaviour changes, update the matching GDD section in the same change, and record significant decisions in the GDD decision log.
