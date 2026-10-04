"""The shapes of the world's records, in one place (D-58). The world is plain JSON-like dicts, saved as patches;
these TypedDicts only name what's in them, for readers and editors. Nothing checks them at run time, and every
field is optional (records grow as play goes on).

    State: the whole world of one journey    Npc: a villager     Person: the stranger or a villager
    Mind: what a villager thinks and knows   Memory, Job: parts of a mind
    Thing: any object in the world           Deal: an agreement with the stranger
"""

from __future__ import annotations

from typing import TypedDict


class Person(TypedDict, total=False):
    """Anyone with a body: the stranger or a villager."""

    x: int  # Grid cell.
    y: int
    alive: bool
    health: float  # 100 is unhurt.
    conditions: list[dict]  # Wounds and their treatment (gear.py, D-49).
    equipped: dict[str, str]  # Slot (right, left, head, body, arms, legs, hands, feet) -> thing id.
    down: bool  # Knocked senseless or disabled: can't act.
    ready_at: dict[str, int]  # Hand -> when it's free again (the stranger, in a fight).
    swings: dict  # Blows winding up (the stranger).


class Memory(TypedDict, total=False):
    """Something a person remembers about the stranger (reputation.py)."""

    kind: str  # violence, theft, breach, demonstration, gift, help, vouch, talk, told, trouble, arrest, alarm
    summary: str  # What happened, as they'd tell it.
    short: str  # A few words: "stole Hessa's bucket".
    severity: int  # 0 (idle talk) .. 3 (a killing)
    clarity: str  # clear, vague, heard, told
    source: str  # witnessed, shown, victim, received, overheard, told_by:<id>, heard:<id>
    victim: str | None  # Who it was done to (a person id).
    item: str | None
    event: int | None  # The event it came from: one memory per event, however many ways they learn of it.
    at: int  # Sim time (ms).
    by: str  # Who spoke for the stranger, or brought word.
    works: bool  # A demonstration: whether the thing did what was claimed.
    wonder: str  # ordinary, clever, uncanny (D-43)
    doubted: bool  # They don't believe it.
    settled: str  # Put right: given back, forgiven, paid for with an arrest (D-46).
    reported: bool  # They've told someone official.


class Job(TypedDict, total=False):
    """What a person is busy doing (cast.set_job): the clock moves them along it (clock.py)."""

    kind: str  # watch, flee, report, approach, attack, fight, encounter, vouch, tell
    target: str  # A person id, or "player".
    goal: list[int]  # A cell, instead of a target.
    speed: str  # walk or run
    stop: float  # How close is there.
    until: int  # When a watch ends (sim ms).
    then: str  # What they do on arriving: halt, confront, threaten, demand_payment, help
    line: str | None  # What they'll say when they get there...
    line_id: str | None  # ...and which authored line it is.
    message: str  # An errand's words (tell).
    why: str  # A vouch's reason.
    summary: str
    event: int
    wait_until: int  # Not before this.
    quiet: bool  # A scripted errand: one written line, no conversation.


class Mind(TypedDict, total=False):
    """What a villager feels, knows and is doing (cast.mind)."""

    memories: list[Memory]
    feelings: dict[str, float]  # fear, anger: 0..1
    regard: dict[str, float]  # trust, suspicion, respect, awe, goodwill_used, illwill_used (reputation.regard)
    standing: str  # The one word the player sees (reputation.STANDING_WORDS).
    job: Job | None
    said: dict | None  # Their latest line: text, at, key.
    talk: list[dict]  # The conversation so far, word for word.
    knows: dict  # Their character sheet's knowledge of the stranger: name, notes, claims (persona.py).
    met: bool
    facing_player: bool
    stirred: dict  # The moment's feelings, held for a while.
    fresh: str  # Something new on their mind: they'll reconsider their day.
    rethinks: int
    mood: str


class Npc(Person, total=False):
    """A villager: who they are comes from their card (data/content/npc_cards.json, cast.card)."""

    id: str
    name: str
    role: str
    injuries: list[str]
    mind: Mind
    controller: dict  # Routine walking: source, activity, path, goal, next_at_ms (npc_sim.py).


class Thing(TypedDict, total=False):
    """Any object in the world: seeded from content (m2.py), made, gathered or cut in play (consequences.py)."""

    id: str
    name: str
    description: str
    x: int
    y: int
    mass_kg: float
    materials: list[str]
    flags: list[str]  # Physical facts: rigid, sharp_edge, container, combustible, tieable...
    capabilities: list[str]  # What code lets you do with it: carry, tie, fill, pour, water_source...
    known_capabilities: list[dict]  # What demonstrations have shown it does.
    owner_id: str | None  # A person id, "player" or None.
    holder_id: str | None  # Who has it (a person id or "player"), None on the ground, "in:<id>" built in.
    lent_to: str  # "player" while it's on loan (D-55).
    condition: str  # usable, installed, used up, broken...
    water_l: float
    capacity_l: float
    temperature: str  # cold, warm, hot, boiling (heat.py)
    burning: bool
    gear: dict  # What it is in a fight or on the body: kind, class, covers, quality (gear.py).
    installed_in: str
    feature: str  # tree, fire...: part of the place rather than a portable thing.
    sprite_asset_id: str  # Its painting.
    created_by: str
    created_text: str  # What the stranger said when they made it.


class Deal(TypedDict, total=False):
    """An agreement with the stranger, from a person's authored offers (GDD 6.6)."""

    id: str
    type: str
    template: str  # The offer's id on the issuer's card.
    issuer: str
    task: str
    check: str
    reward: str
    status: str  # proposed, accepted, fulfilled
    offered_event: int
    accepted_event: int
    fulfilled_event: int


class State(TypedDict, total=False):
    """The whole world of one journey, as rebuilt from its events (store.py)."""

    run_id: str
    mode: str  # normal or developer
    scenario: str  # village or tutorial
    seed_version: int
    event_seq: int  # The latest event.
    player_seq: int  # The latest event the player caused (stale-request checks).
    tick: int
    sim_time_ms: int
    player: Person
    npcs: list[Npc]
    objects: dict[str, Thing]
    agreements: dict[str, Deal]
    trades: dict[str, dict]
    journal: list[dict]
    learned: list[dict]  # Leads: what the stranger has learned (the journal's pages).
    pending_minds: list[dict]  # Who has something to think about: npc_id, kind, why.
    encounter: dict | None  # Face to face, in rounds (encounter.py).
    fight: dict | None  # Real-time fighting (combat.py).
    projectiles: list[dict]
    gate_open: bool
    admitted: dict | None  # Who let the stranger in, and why.
    barred_until: int
    safe_seq: int  # The latest calm moment, to rewind to.
    last_action: dict | None
    last_round: dict | None
    tutorial: dict  # A guided level's progress (scenario.py).
    device_log: list[dict]
    village: dict
    water_spilled_l: float
