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
