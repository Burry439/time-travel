"""Content is checked the way code would read it (D-58): every rule is a known kind with the fields it needs,
everyone and everything a rule names exists, and every authored thing and person has what the game reads. Every
map and level is checked the same way (D-59): places, starts and people's rounds on open ground, everyone in a
cast with a card. Adding a condition or effect kind means registering it (rules.condition, scenario.effect) with
its fields."""

import pytest

import content
import conversation
import gear
import paths
import rules
import scenario

try:  # The parked storylines (D-56) register their own kinds when they're present.
    import stories
except ImportError:  # pragma: no cover - not in every checkout
    stories = None

CARDS, LEVELS, MAPS = content.CARDS, content.LEVELS, content.MAPS
GUIDED = {level_id: level for level_id, level in LEVELS.items() if level.get("steps")}


def things_in(level: dict) -> set[str]:
    """Every thing in a level at the start: its own and its map's trees."""
    trees = {o.get("id") or o["name"].lower() for o in MAPS[level["map"]]["obstacles"] if o.get("tree")}
    return {spec["id"] for spec in level["things"]} | trees


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


def level_rules(level: dict):
    """(conditions, effects) of a guided level, each with where it is."""
    conditions, effects = [], []
    for step in level["steps"]:
        conditions.append((step["check"], f"{step['id']}.check"))
        if step.get("words_check"):
            conditions.append((step["words_check"], f"{step['id']}.words_check"))
        lists = [
            (step.get("on_start", []), f"{step['id']}.on_start"),
            (step.get("on_done", []), f"{step['id']}.on_done"),
        ]
        lists += [(t["do"], f"{step['id']}:{t['id']}.do") for t in step.get("triggers", [])]
        conditions += [(t["when"], f"{step['id']}:{t['id']}.when") for t in step.get("triggers", [])]
        for items, where in lists:
            for index, effect in enumerate(items):
                effects.append((effect, f"{where}[{index}]"))
                for key in ("when", "done_when"):
                    if effect.get(key):
                        conditions.append((effect[key], f"{where}[{index}].{key}"))
                for key in ("why", "summary"):
                    conditions += list(text_conditions(effect.get(key), f"{where}[{index}].{key}"))
    for role in level.get("roles", []):
        if isinstance(role.get("stays"), dict):
            conditions.append((role["stays"], f"role {role['npc']}.stays"))
    for name, speech in level.get("speeches", {}).items():
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
    """Every rule in content, each with where it is: (conditions, effects)."""
    conditions, effects = list(card_conditions()), []
    for level_id, level in GUIDED.items():
        level_conditions, level_effects = level_rules(level)
        conditions += [(c, f"{level_id}: {where}") for c, where in level_conditions]
        effects += [(e, f"{level_id}: {where}") for e, where in level_effects]
    story_conditions, story_effects = story_rules()
    return conditions + story_conditions, effects + story_effects


def test_every_rule_is_a_known_kind_with_what_it_needs():
    conditions, effects = all_rules()
    assert conditions and effects
    speeches = {name for level in GUIDED.values() for name in level.get("speeches", {})}
    problems = []
    for top, where in conditions:
        for spec, at in conditions_in(top, where):
            kind = spec.get("kind")
            if kind not in rules.CONDITIONS:
                problems.append(f"{at}: unknown condition {kind!r}")
            else:
                problems += [f"{at}: {kind} needs {field}" for field in rules.NEEDS[kind] if field not in spec]
            if kind == "made" and not (spec.get("named") or spec.get("from") or spec.get("gear")):
                problems.append(f"{at}: made needs named words, from things or gear kinds")
    for spec, at in effects:
        kind = spec.get("kind")
        if kind not in scenario.EFFECTS:
            problems.append(f"{at}: unknown effect {kind!r}")
        else:
            problems += [f"{at}: {kind} needs {field}" for field in scenario.NEEDS[kind] if field not in spec]
        if kind == "vouch" and not (spec.get("speech") in speeches or "why" in spec):
            problems.append(f"{at}: a vouch needs a speech or its own words")
    assert not problems, "\n".join(problems)


def named_in(spec: dict, at: str, people: set[str], things: set[str]) -> list[str]:
    """What a rule names that isn't there: people (npc ids) and things."""
    problems = []
    people_keys = ("npc", "from", "by", "to", "of") + (("with",) if spec.get("kind") == "hold" else ())
    for key in people_keys:  # A hold's "with" is people; a spar's is the practice weapon.
        value = spec.get(key)
        for npc_id in value if isinstance(value, list) else [value]:
            if isinstance(npc_id, str) and npc_id.startswith("npc_") and npc_id not in people:
                problems.append(f"{at}: {key} {npc_id} isn't anyone here")
    weapon = spec.get("with") if spec.get("kind") == "spar" else None
    for thing in spec.get("objects", []) + [spec.get("thing"), weapon]:
        if thing and thing not in things:
            problems.append(f"{at}: no thing {thing}")
    return problems


@pytest.mark.parametrize("level_id", sorted(GUIDED))
def test_everyone_and_everything_a_level_names_is_in_it(level_id):
    level = GUIDED[level_id]
    people, things = set(level["cast"]), things_in(level)
    conditions, effects = level_rules(level)
    named = [(spec, at) for top, where in conditions for spec, at in conditions_in(top, where)] + effects
    problems = [problem for spec, at in named for problem in named_in(spec, at, people, things)]
    step_ids = [step["id"] for step in level["steps"]]
    for role in level.get("roles", []):
        assert role["npc"] in people and set(role["during"]) <= set(step_ids), role
        assert set(role.get("withholds", [])) <= {"go_tell", "vouch", "call_guard", "admit", "refer", "lend", "give"}
        assert not role.get("spars") or role["spars"]["with"] in things, role
    assert len(set(step_ids)) == len(step_ids), "step ids repeat"
    for step in level["steps"]:
        ids = [t["id"] for t in step.get("triggers", [])]
        assert len(set(ids)) == len(ids), f"{step['id']}: trigger ids repeat"
    assert not problems, "\n".join(problems)


def test_everyone_and_everything_a_card_names_exists():
    conditions = list(card_conditions()) + story_rules()[0]
    everything = {thing for level in LEVELS.values() for thing in things_in(level)}
    named = [(spec, at) for top, where in conditions for spec, at in conditions_in(top, where)]
    problems = [problem for spec, at in named for problem in named_in(spec, at, set(CARDS), everything)]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("map_id", sorted(MAPS))
def test_every_map_is_whole(map_id):
    plan = MAPS[map_id]
    width, height = plan["size"]
    x0, y0, x1, y1 = plan["walk"]
    assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height, "walk lies outside the map"
    for item in plan["buildings"] + plan["obstacles"]:
        bx, by, w, h = item["cells"]
        assert bx >= 0 and bx + w <= width and by >= 0 and by + h <= height, item["name"]
        assert not item.get("tree") or item["tree"] in plan["trees"], item["name"]
    grid = paths.standing_grid({"scenario": next(i for i, lv in LEVELS.items() if lv["map"] == map_id)})
    assert not [p for p, v in plan["places"].items() if not grid.walkable(tuple(v["cell"]))], "a place isn't open"


@pytest.mark.parametrize("level_id", sorted(LEVELS))
def test_every_level_stands_on_open_ground(level_id):
    level = LEVELS[level_id]
    assert level["map"] in MAPS and level["objective"]
    grid = paths.standing_grid({"scenario": level_id})
    assert grid.walkable(tuple(level["start"]["cell"])), "the stranger starts in a wall"
    for npc_id, spec in level["cast"].items():
        assert all(grid.walkable((x, y)) for x, y, _, _ in spec["anchors"]), npc_id
    width, height = MAPS[level["map"]]["size"]
    for spec in level["things"]:
        if "x" in spec:
            assert 0 <= spec["x"] < width and 0 <= spec["y"] < height, spec["id"]
    if level.get("steps"):
        assert level["version"] and level["reactions"]


@pytest.mark.parametrize("level_id", sorted(LEVELS))
def test_every_level_file_names_its_map_and_goal_itself(level_id):
    """The client reads level files as they are (its map scene, the HUD's goal), without following base."""
    raw = content.read(f"content/levels/{level_id}.json")
    assert raw["id"] == level_id and raw["map"] in MAPS and raw["goal"] and raw["title"]


@pytest.mark.parametrize(
    ("level_id", "npc_id"), sorted((level_id, npc_id) for level_id, level in LEVELS.items() for npc_id in level["cast"])
)
def test_everyone_in_a_level_has_a_card_a_title_a_pace_and_a_day(level_id, npc_id):
    routine, card = LEVELS[level_id]["cast"][npc_id], CARDS.get(npc_id)
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
    for level_id, level in LEVELS.items():
        ids = [spec["id"] for spec in level["things"]]
        assert len(set(ids)) == len(ids), f"{level_id}: thing ids repeat"
    specs = {spec["id"]: spec for level in LEVELS.values() for spec in level["things"]}.values()
    everything = {thing for level in LEVELS.values() for thing in things_in(level)}
    for spec in specs:
        for field in ("id", "name", "mass_kg", "materials", "description", "flags"):
            assert field in spec, f"{spec.get('id')}: {field}"
        unknown = set(spec["flags"]) - set(content.MATERIALS["flag_meanings"])
        assert not unknown, f"{spec['id']}: flags the judge doesn't know: {unknown}"
        assert ("x" in spec and "y" in spec) or spec.get("carried_by") or spec.get("worn_by"), spec["id"]
        for key in ("owner_id", "carried_by", "worn_by"):
            assert spec.get(key) in (None, "player") or spec[key] in CARDS, f"{spec['id']}: {key}"
        record = spec.get("gear")
        if record and record["kind"] in tables:
            assert record["class"] in tables[record["kind"]], f"{spec['id']}: no {record['kind']} {record['class']}"
        if spec.get("installed_in"):
            assert spec["installed_in"] in everything, spec["id"]


@pytest.mark.parametrize("level_id", sorted(GUIDED))
def test_every_playtest_names_what_is_in_its_level(level_id):
    """Each step's playtest (tools/playtest_level.gd, evals/run_level_words.py) can only do what the level has."""
    level = GUIDED[level_id]
    people, things = set(level["cast"]), things_in(level)
    for step in level["steps"]:
        scripts = [step.get("playtest", []), *step.get("routes", {}).values()]  # Every route an advanced level has.
        for action in (action for script in scripts for action in script):
            target = action.get("walk_to")
            assert target is None or isinstance(target, list) or target in people | things, (step["id"], action)
            assert action.get("take") in (None, *things), (step["id"], action)
            assert action.get("to") in (None, *people), (step["id"], action)
            assert action.get("ui") in (None, "pack", "inspect", "journal", "book"), (step["id"], action)
    if any(step.get("playtest") for step in level["steps"]):  # Scripted (the first morning has its own script).
        missing = [s["id"] for s in level["steps"] if s.get("task") and not s.get("playtest")]
        assert not missing, f"steps with a task but no playtest: {missing}"


def test_every_map_scene_lets_clicks_through():
    """A map's ground, bands and blocks are pictures, not controls: one that took the mouse would swallow every click
    on the world (D-59: no right-click worked in the training levels)."""
    for scene in sorted((content.ROOT / "scenes" / "maps").glob("*.tscn")):
        for block in scene.read_text(encoding="utf-8").split("\n\n"):
            if 'type="ColorRect"' in block or 'type="TextureRect"' in block:
                assert "mouse_filter = 2" in block, f"{scene.name}: {block.splitlines()[0]}"
