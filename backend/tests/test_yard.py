"""The old wainwright's yard (seed 11, D-51): a free stock of materials in the bottom-right corner, every piece on an
open cell the stranger can walk to, unowned, and read by code for what it would be in a fight."""

import json

from test_talk import unit_state

import paths
import store


def test_the_yard_is_free_reachable_and_read_for_a_fight():
    state = unit_state()
    yard = [o for o in state["objects"].values() if o["id"].startswith("yard_")]
    assert len(yard) >= 40 and state["seed_version"] >= 11
    blocked = paths.grid(state)
    _, steps = paths.bfs((state["player"]["x"], state["player"]["y"]), blocked, 400)
    cells = set()
    for obj in yard:
        cell = (obj["x"], obj["y"])
        assert cell not in blocked and cell not in cells, obj["id"]
        assert cell in steps, f"{obj['id']} can't be reached"
        assert obj["owner_id"] is None and "carry" in obj["capabilities"] and "gear" in obj, obj["id"]
        assert 74 <= obj["x"] <= 93 and 50 <= obj["y"] <= 70  # The bottom-right corner.
        cells.add(cell)


def test_the_wainwrights_notebook_is_readable_and_names_real_things():
    """D-52: a readable object at the yard's edge (seed 12), and a book whose every ingredient is something in
    the world, named as it lies there."""
    state = unit_state()
    book = state["objects"]["yard_recipe_book"]
    assert book["readable"] == "recipe_book" and book["owner_id"] is None and "carry" in book["capabilities"]
    blocked = paths.grid(state)
    _, steps = paths.bfs((state["player"]["x"], state["player"]["y"]), blocked, 400)
    assert (book["x"], book["y"]) in steps
    content = json.loads((store.ROOT / "data" / "content" / "recipe_book.json").read_text(encoding="utf-8"))
    names = {o["name"] for o in state["objects"].values()}
    recipes = [r for chapter in content["chapters"] for r in chapter["recipes"]]
    assert len(recipes) >= 30 and content["intro"]
    for recipe in recipes:
        assert recipe["steps"] and recipe["say"] and recipe["good_for"], recipe["name"]
        for need in recipe["need"]:
            assert need.split(" (")[0] in names, (recipe["name"], need)
        text = " ".join([recipe["say"], *recipe["steps"]]).lower()
        assert not any(w in text for w in ("gate", "compass", "magnet", "beam")), recipe["name"]  # No city routes.


def test_the_stranger_starts_with_survival_notes_that_quote_the_worlds_own_facts():
    """Basics for a world without matches (D-72). Each page's facts are the judge's own material facts, and the book
    names no way into the city."""
    import content as world_content

    state = unit_state()
    book = state["objects"]["survival_book"]
    assert book["holder_id"] == "player" and book["readable"] == "survival_book" and book["owner_id"] == "player"
    notes = json.loads((store.ROOT / "data" / "content" / "survival_book.json").read_text(encoding="utf-8"))
    facts = world_content.MATERIALS["material_facts"]
    pages = [page for chapter in notes["chapters"] for page in chapter["recipes"]]
    assert notes["made_chapter"] and notes["intro"] and len(pages) >= 8
    for page in pages:
        assert page["steps"] and page["say"] and page["good_for"] and page["need"], page["name"]
        assert page["facts"] and all(key in facts for key in page["facts"]), page["name"]
        text = " ".join([page["say"], *page["steps"]]).lower()
        assert not any(w in text for w in ("gate", "compass", "magnet", "beam", "city")), page["name"]


def test_every_source_agrees_that_fire_needs_steel_not_plain_iron():
    """The judge refused flint on iron while the device advised it and one material fact allowed it (D-72). The
    judge's prompt, the material facts and the survival notes now say one thing."""
    import content as world_content
    from ai import judge

    facts = world_content.MATERIALS["material_facts"]
    for key in ("flint", "iron", "steel", "fire"):
        assert "steel" in facts[key], key
    assert "no spark" in facts["iron"] and "Plain iron or stone struck on flint will not light it" in facts["fire"]
    assert "flint against iron" not in judge._PROMPT and "material_facts (flint, iron, steel, fire)" in judge._PROMPT
    notes = (store.ROOT / "data" / "content" / "survival_book.json").read_text(encoding="utf-8")
    assert "plain iron won't do" in notes
