"""Content is checked the way code would read it (D-58): every rule is a known kind with the fields it needs,
everyone and everything a rule names exists, and every authored thing and person has what the game reads.
Adding a condition or effect kind means registering it (rules.condition, scenario.effect) with its fields."""

import pytest

import content
import conversation
import gear
import rules
import scenario

try:  # The parked storylines (D-56) register their own kinds when they're present.
    import stories
except ImportError:  # pragma: no cover - not in every checkout
    stories = None

CARDS, ROUTINES, TUTORIAL = content.CARDS, content.ROUTINES, content.TUTORIAL
STEP_IDS = [step["id"] for step in TUTORIAL["steps"]]
THINGS = {spec["id"] for spec in content.WORLD_OBJECTS["objects"]} | {t["id"] for t in TUTORIAL.get("things", [])}


def conditions_in(spec, where: str):
    """Every condition in a condition (all/any/not open up), with where it is."""
    yield spec, where
    if spec.get("kind") in ("all", "any"):
        for index, part in enumerate(spec.get("of", [])):
            yield from conditions_in(part, f"{where}.of[{index}]")
    elif spec.get("kind") == "not":
        yield from conditions_in(spec["of"], f"{where}.of")


def text_conditions(parts, where: str):
    """Conditions inside words written in parts ({text, when})."""
    for index, part in enumerate(parts if isinstance(parts, list) else []):
        if isinstance(part, dict) and part.get("when"):
            yield part["when"], f"{where}[{index}].when"


def tutorial_rules():
    """(conditions, effects) of the first morning, each with where it is."""
    conditions, effects = [], []
    for step in TUTORIAL["steps"]:
        conditions.append((step["check"], f"{step['id']}.check"))
        lists = [
            (step.get("on_start", []), f"{step['id']}.on_start"),
            (step.get("on_done", []), f"{step['id']}.on_done"),
        ]
        lists += [(t["do"], f"{step['id']}:{t['id']}.do") for t in step.get("triggers", [])]
        conditions += [(t["when"], f"{step['id']}:{t['id']}.when") for t in step.get("triggers", [])]
        for items, where in lists:
            for index, effect in enumerate(items):
                effects.append((effect, f"{where}[{index}]"))
                if effect.get("when"):
                    conditions.append((effect["when"], f"{where}[{index}].when"))
                for key in ("why", "summary"):
                    conditions += list(text_conditions(effect.get(key), f"{where}[{index}].{key}"))
    for role in TUTORIAL.get("roles", []):
        if isinstance(role.get("stays"), dict):
            conditions.append((role["stays"], f"role {role['npc']}.stays"))
    for name, speech in TUTORIAL.get("speeches", {}).items():
        conditions += [(c, f"speech {name}.notes.{key}") for key, c in speech.get("notes", {}).items()]
        for key in ("why", "summary"):
            conditions += list(text_conditions(speech.get(key), f"speech {name}.{key}"))
    return conditions, effects


def card_conditions():
    for npc_id, card in CARDS.items():
        for offer in card.get("offers", []):
            if offer.get("done_when"):
                yield offer["done_when"], f"{npc_id} offer {offer['id']}.done_when"
        for task in card.get("tasks", []):
            for key in ("when", "unless"):
                if task.get(key):
                    yield task[key], f"{npc_id} task {task['id']}.{key}"
        for secret in card.get("secrets", []):
            if secret.get("unlock"):
                yield secret["unlock"], f"{npc_id} secret {secret.get('id')}.unlock"


def story_rules():
    if stories is None:
        return [], []
    conditions, effects = [], []
    for story in stories.STORIES.values():
        for part in story.get("stages", []) + story.get("outcomes", []):
            conditions.append((part["when"], f"story {story['id']}.{part['id']}"))
            effects += [(e, f"story {story['id']}.{part['id']}.effects") for e in part.get("effects", [])]
    conditions += [(m["when"], f"move {m['id']}") for m in stories.MOVES.values()]
    return conditions, effects


def all_rules():
    tutorial_conditions, tutorial_effects = tutorial_rules()
    story_conditions, story_effects = story_rules()
    return tutorial_conditions + list(card_conditions()) + story_conditions, tutorial_effects + story_effects


def test_every_rule_is_a_known_kind_with_what_it_needs():
    conditions, effects = all_rules()
    assert conditions and effects
    problems = []
    for top, where in conditions:
        for spec, at in conditions_in(top, where):
            kind = spec.get("kind")
            if kind not in rules.CONDITIONS:
                problems.append(f"{at}: unknown condition {kind!r}")
            else:
                problems += [f"{at}: {kind} needs {field}" for field in rules.NEEDS[kind] if field not in spec]
    for spec, at in effects:
        kind = spec.get("kind")
        if kind not in scenario.EFFECTS:
            problems.append(f"{at}: unknown effect {kind!r}")
        else:
            problems += [f"{at}: {kind} needs {field}" for field in scenario.NEEDS[kind] if field not in spec]
        if kind == "vouch" and not (spec.get("speech") in TUTORIAL.get("speeches", {}) or "why" in spec):
            problems.append(f"{at}: a vouch needs a speech or its own words")
    assert not problems, "\n".join(problems)


def test_everyone_and_everything_a_rule_names_exists():
    conditions, effects = all_rules()
    problems = []
    named = [(spec, at) for top, where in conditions for spec, at in conditions_in(top, where)] + effects
    for spec, at in named:
        people_keys = ("npc", "from", "by", "to", "of") + (("with",) if spec.get("kind") == "hold" else ())
        for key in people_keys:  # A hold's "with" is people; a spar's is the practice weapon.
            value = spec.get(key)
            for npc_id in value if isinstance(value, list) else [value]:
                if isinstance(npc_id, str) and npc_id.startswith("npc_") and npc_id not in CARDS:
                    problems.append(f"{at}: {key} {npc_id} isn't anyone")
        weapon = spec.get("with") if spec.get("kind") == "spar" else None
        for thing in spec.get("objects", []) + [spec.get("thing"), weapon]:
            if thing and thing not in THINGS:
                problems.append(f"{at}: no thing {thing}")
    for role in TUTORIAL.get("roles", []):
        assert role["npc"] in CARDS and set(role["during"]) <= set(STEP_IDS), role
        assert set(role.get("withholds", [])) <= {"go_tell", "vouch", "call_guard", "admit", "refer", "lend", "give"}
        assert role.get("spars", {}).get("with", "practice_sword_kade") in THINGS
    assert len(set(STEP_IDS)) == len(STEP_IDS), "step ids repeat"
    for step in TUTORIAL["steps"]:
        ids = [t["id"] for t in step.get("triggers", [])]
        assert len(set(ids)) == len(ids), f"{step['id']}: trigger ids repeat"
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("npc_id", sorted(ROUTINES))
def test_everyone_in_the_world_has_a_card_a_title_a_pace_and_a_day(npc_id):
    routine, card = ROUTINES[npc_id], CARDS.get(npc_id)
    assert card and card["name"] and card["role"] and card["personality"] and card["tones"]
    assert routine["role"] and routine["step_ms"] > 0 and routine["goal"] and routine["anchors"]
    assert all(len(anchor) == 4 for anchor in routine["anchors"])
    for offer in card.get("offers", []):
        assert offer["id"] and offer["task"] and offer["check"] and offer["reward"] in conversation.REWARDS
    for fact in card.get("knowledge", {}).values():
        assert fact["text"]


def test_every_authored_thing_has_what_the_game_reads():
    tables = {
        "weapon": gear.WEAPONS,
        "armour": gear.ARMOUR,
        "clothing": gear.ARMOUR,
        "shield": gear.SHIELDS,
        "remedy": gear.REMEDIES,
    }
    specs = content.WORLD_OBJECTS["objects"] + TUTORIAL.get("things", [])
    ids = [spec["id"] for spec in specs]
    assert len(set(ids)) == len(ids), "thing ids repeat"
    for spec in specs:
        for field in ("id", "name", "mass_kg", "materials", "description", "flags"):
            assert field in spec, f"{spec.get('id')}: {field}"
        assert ("x" in spec and "y" in spec) or spec.get("carried_by") or spec.get("worn_by"), spec["id"]
        for key in ("owner_id", "carried_by", "worn_by"):
            assert spec.get(key) in (None, "player") or spec[key] in CARDS, f"{spec['id']}: {key}"
        record = spec.get("gear")
        if record and record["kind"] in tables:
            assert record["class"] in tables[record["kind"]], f"{spec['id']}: no {record['kind']} {record['class']}"
        if spec.get("installed_in"):
            assert spec["installed_in"] in THINGS, spec["id"]
