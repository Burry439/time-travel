"""The numbers that set the game's feel, in one place: how far people see and hear, how fast they walk, how
trust grows, how long things take. Code reads them from here; change one and the rule changes everywhere
(GDD section 8, D-58). Word lists, kinds and storage limits stay with the code that uses them."""

from __future__ import annotations

# --- Seeing and hearing (in cells; a cell is about a pace) -----------------------------------------------------------

SIGHT_CELLS = 20.0  # D-55: doubled (was 10).
CLEAR_VIEW_CELLS = (
    10.0  # Closer than this, a witness sees exactly what happened; further, only a scuffle (D-55: was 5).
)
AMBIENT_CELLS = 16.0  # Wary people turn to face the stranger within this range (D-55: was 8).
BARK_CELLS = 8.0  # Close enough to shout at the stranger the moment it happens.
HEAR_SHOUT_CELLS = 30.0  # A shout for help carries across the open road.
WARN_CELLS = 12.0
WHISTLE_CELLS = 45.0
HEAR_TALK_CELLS = 5.0  # GDD 7.3: normal speech carries 5 cells.
OVERHEAR_CELLS = 5.0
WITNESS_RADIUS = 20.0  # Cells within which people are recorded as witnesses (D-55: was 10).
PEOPLE_RADIUS = 8.0  # Cells within which the judge is told about people.

# --- Reach and walking -----------------------------------------------------------------------------------------------

REACH_CELLS = 2.5
REACH_TAKE = 2.0  # Close enough to take something out of the stranger's hands.
TALK_CELLS = 3.0  # Close enough to talk without walking over.
MEET_CELLS = 3.0  # Close enough to fall into conversation.
HELP_CELLS = 5.0  # Close enough to lend a hand with something heavy: to the stranger, or to the thing (D-59).
VISIT_REACH = 3.0
NEARBY_WALK_STEPS = 14  # Things this many steps away can be acted on; the player walks there first.
WALK_CELLS_PER_SECOND = 7.1875  # Matches the backend walking speed.
RUN_STEP_MS = 170
WALK_STEP_MS = 400
GIVE_UP_CELLS = 28.0
THROW_RANGE = 8.0  # Cells.
MAX_THROW_KG = 5.0
CARRY_LIMIT_KG = 20.0

# --- The gate --------------------------------------------------------------------------------------------------------

GATE_HOLD_CELLS = 8.0  # A guard standing this close steps into the gap to stop anyone walking through.
HALT_REACH_CELLS = 14.0
HALT_EVERY_MS = 180_000  # A stranger who was stopped isn't stopped again for a while.
DEALT_WITH_MS = 60_000  # The stranger just talked to or showed something to a guard: nobody needs to halt them.
BARRED_MS = 600_000  # How long the guards keep an arrested stranger away from the gate.
MIN_GATE_GUARDS = 2  # The gate is never left with fewer guards than this.

# --- Minds: memory, thinking, feelings -------------------------------------------------------------------------------

MEMORY_LIMIT = 12
MAX_RETHINKS = 2  # Automatic reconsiderations per person after their latest memory.
THINK_BATCH = 6  # People who can think in one /think call (one decider request); the rest wait for the next.
WATCH_MS = 20_000  # After a fright, a fight or a flight, someone keeps an eye on the stranger this long...
WATCH_SHORT_MS = 15_000  # ...and after passing news on or a conversation ending, a little less.
STIRRED_MS = 20_000  # How long the feelings of that moment last before they can cool.

# --- Regard: how people come to see the stranger ---------------------------------------------------------------------

TRUST_BANDS = (0.3, 0.45, 0.6, 0.75)  # Crossing one of these shows as a small in-character cue.
SUSPICION_BANDS = (0.4, 0.6, 0.8)
EVIDENCE_SHIFT = 0.15  # Regard change for one clear piece of evidence (or, doubled, one crime).
RESPECT_SHIFT = {"ordinary": EVIDENCE_SHIFT, "clever": 2 * EVIDENCE_SHIFT, "uncanny": EVIDENCE_SHIFT}
AWE_SHIFT = 0.25
HEARSAY_SHIFT = 0.05  # How much one person's view of the stranger rubs off on another (once per teller).
TALK_GOODWILL = 0.3  # How far words alone can raise trust (or lower suspicion) with one person.
TALK_ILLWILL = 0.3  # ...and how far words alone can lower it (D-46: symmetric; deeds and crimes count in full).
EVIDENCE_GOODWILL = 0.3  # Each new piece of evidence they hold about the stranger allows this much more.
SHIFTS = [-0.15, -0.07, 0.0, 0.07, 0.15]
WARMTH_SHIFTS = [-0.1, -0.05, 0.0, 0.05, 0.1]
# How far one moment of a conversation can move someone's feelings toward someone else (D-59: brothers made up).
OPINION_SHIFTS = {"Much worse": -0.3, "A little worse": -0.15, "A little better": 0.15, "Much better": 0.3}

# --- What people will do for the stranger ----------------------------------------------------------------------------

SHARE_TRUST = 0.45  # Facts marked "trusted" are only told to someone trusted at least this much.
GIVE_TRUST = 0.45  # Someone gives a stranger their things only once they trust them this much.
VOUCH_TRUST = 0.6  # Someone must trust the stranger this much to vouch unasked.
DONE_YES = 0.6  # How sure the decider must be that a deal was done.
REASON_YES = 0.45  # The captain admits when he believes there is a legitimate reason...
THREAT_NO = 0.5  # ...and doesn't believe the stranger is a threat (two simple beliefs beat one compound one).

# --- Time: conversations, rounds, the village's own life -------------------------------------------------------------

TALK_SECONDS = 5  # GDD 4.6: one conversation turn.
TALK_WATCH_MS = 20_000  # The person stays and faces the stranger this long after each exchange.
ROUND_MS = 5_000
FIGHT_WORDS_MS = 2_000  # Words shouted mid-fight take a moment, not a whole round (D-51).
LEAVE_MS = 1_000  # Walking away takes a moment.
AGENDA_GAP_MS = 20_000  # Something fresh makes a free person reconsider their day, at most this often (D-39).
MEET_GAP_MS = 120_000  # Nobody stops for another chat within this long of their last one.
PAIR_GAP_MS = 600_000  # The same two don't fall into small talk again this soon, unless one has news (D-48).
CHAT_MS = 8_000
CHATTER_PER_MINUTE = 2  # Voiced meetings (only when the stranger can see them).
MOMENT_GAP_MS = 120_000  # The device speaks up on its own at most this often (D-55).

# --- Fighting and hurt -----------------------------------------------------------------------------------------------

WOUND_DAMAGE = 45
DISABLED_HEALTH = 20  # Down and out of the fight, but alive (D-41).
SUBDUE_DAMAGE = 15  # A spear butt, a fist, a shove to the ground: hurts, doesn't kill (D-44).
SUBDUED_AT = 25  # Beaten down to this, the stranger is at their mercy: a guard arrests them; anyone else stops.
SPAR_ENOUGH_AT = 40  # A sparring partner beaten down to this calls it: "Enough!" (D-50).
SPAR_MAX_BLOW = 12  # Practice blows are pulled: they bruise, never cut or break.
HIT_RADIUS = 0.8  # A missile hits someone within this of where it was aimed when it arrives.

# --- Things: effort, gathering, heat and fire ------------------------------------------------------------------------

MAX_EFFORT_SECONDS = 14_400  # Felling a large tree by hand can take hours.
GATHER_MAX_KG = 1.0  # A part taken off something larger: a leaf, a twig, a strip of bark, a handful (D-48).
COOLING_MS = {"boiling": 120_000, "hot": 300_000, "warm": 600_000}  # How long each lasts off the fire.
FIRE_MS_PER_KG = 600_000  # A made fire burns about ten minutes per kilogram of fuel...
FIRE_MS_RANGE = (120_000, 1_800_000)  # ...between two and thirty minutes.
