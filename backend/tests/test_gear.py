"""The gear table and what blows do to bodies (D-49): realistic, fixed, no dice."""

import gear


def thing(
    name, materials, mass, length=None, flags=("rigid",), cls=None, kind="weapon", covers=(), quality="fair", oid=None
):
    obj = {
        "id": oid or name.replace(" ", "_"),
        "name": name,
        "materials": list(materials),
        "mass_kg": mass,
        "length_m": length,
        "flags": list(flags),
    }
    if cls:
        obj["gear"] = {"kind": kind, "class": cls, "covers": list(covers), "quality": quality}
    return obj


def person(state, armour=(), health=100):
    """Someone wearing these things (added to the world)."""
    who = {"id": "p", "health": health, "alive": True, "equipped": {}}
    for obj in armour:
        state["objects"][obj["id"]] = {**obj, "holder_id": "p"}
        for slot in obj["gear"]["covers"]:
            who["equipped"][slot] = obj["id"]
    return who


SWORD = thing("iron sword", ["iron", "wood", "leather"], 1.3, 1.0, ("rigid", "sharp_edge"), "long_sword")
WOOD_SPEAR = thing("fire-hardened spear", ["wood"], 1.5, 1.9, ("rigid", "sharp_edge"), "short_spear")
ROCK = thing("rock", ["stone"], 1.5, 0.15, ("rigid",), "hand_stone")
MAIL = thing("mail shirt", ["iron"], 10.0, None, ("flexible",), "mail", "armour", ("body",))
HELM = thing("iron helmet", ["iron"], 1.5, None, ("rigid",), "helmet", "armour", ("head",))


def test_an_iron_sword_kills_the_unarmoured_in_two_and_they_bleed():
    state = {"objects": {}}
    target = person(state)
    blow = gear.hit(state, target, gear.weapon(SWORD))
    assert blow["effective"] == 60 and any(c["kind"] == "bleeding" and c["heavy"] for c in blow["conditions"])
    gear.apply(target, blow, 0)
    assert gear.apply(target, gear.hit(state, target, gear.weapon(SWORD)), 0) == "killed"


def test_a_wooden_spear_is_dangerous_bare_and_useless_against_mail():
    state = {"objects": {}}
    spear = gear.weapon(WOOD_SPEAR)
    assert 25 <= spear["damage"] <= 30
    assert gear.hit(state, person(state), spear)["effective"] >= 25
    armoured = person(state, [MAIL])
    blow = gear.hit(state, armoured, spear)
    assert blow["deflected"] and blow["effective"] <= 5 and blow["result"] == "deflected"
    iron = gear.hit(state, armoured, gear.weapon(SWORD))
    assert 0 < iron["effective"] < 10  # Mail stops most of even a sword's cut.


def test_a_rock_to_the_head_of_someone_unaware_drops_them_but_a_plain_blow_does_not():
    state = {"objects": {}}
    sneak = gear.hit(state, person(state), gear.weapon(ROCK), area="head", aware=False)
    assert sneak["effective"] >= 70 and sneak["knockout"]
    plain = gear.hit(state, person(state), gear.weapon(ROCK))
    assert plain["effective"] == 25 and not plain["knockout"]
    helmeted = gear.hit(state, person(state, [HELM]), gear.weapon(ROCK), area="head", aware=False)
    assert helmeted["effective"] < sneak["effective"]


def test_a_knife_to_the_throat_of_someone_unaware_kills_but_not_a_facing_guard():
    state = {"objects": {}}
    knife = gear.weapon(thing("iron knife", ["iron", "wood"], 0.3, 0.25, ("rigid", "sharp_edge"), "knife"))
    assert gear.hit(state, person(state), knife, area="neck", aware=False)["kill"]
    assert not gear.hit(state, person(state), knife, area="neck", aware=True)["kill"]


def test_a_strangle_needs_them_unaware_and_time():
    state = {"objects": {}}
    rope = gear.weapon(thing("rope", ["plant fiber"], 1.0, 3.0, ("flexible", "tieable")))
    assert gear.hit(state, person(state), rope, family="choke", aware=True, held_seconds=200)["result"] == "missed"
    assert gear.hit(state, person(state), rope, family="choke", aware=False, held_seconds=20)["result"] == "knocked_out"
    assert gear.hit(state, person(state), rope, family="choke", aware=False, held_seconds=150)["kill"]


def test_boiling_water_blinds_and_burns_cold_water_only_soaks():
    state = {"objects": {}}
    boiled = gear.hit(state, person(state), {}, family="pour", liquid={"temperature": "boiling"})
    assert boiled["down"] and any(c["kind"] == "burn" for c in boiled["conditions"])
    assert gear.hit(state, person(state), {}, family="pour", liquid={"temperature": "cold"})["effective"] == 0


def test_bleeding_kills_untreated_and_stitches_stop_it():
    state = {"objects": {}}
    left = person(state)
    gear.apply(left, gear.hit(state, left, gear.weapon(SWORD), area="arm"), 0)
    assert gear.untreated(left)
    for minute in range(30):
        gear.advance(left, 60_000, minute * 60_000)
    assert not left["alive"]
    saved = person(state)
    gear.apply(saved, gear.hit(state, saved, gear.weapon(SWORD), area="arm"), 0)
    leaves = thing("leaf bandage", ["leaf"], 0.05, None, ("flexible",), "bandage", "remedy", quality="crude")
    gear.treat(saved, 0, leaves, 0)
    assert gear.bleed_rate(saved["conditions"][0]) > 0  # Leaves only slow a deep cut.
    stitches = thing("needle and thread", ["iron", "flax thread"], 0.02, None, (), "stitches", "remedy")
    assert gear.treat(saved, 0, stitches, 0)["ok"]
    health = saved["health"]
    gear.advance(saved, 5 * 60_000, 0)
    assert saved["alive"] and saved["health"] >= health  # Closed: it mends now.


def test_a_burn_festers_untreated_and_a_poultice_answers_the_infection():
    state = {"objects": {}}
    burnt = person(state)
    gear.apply(burnt, {"effective": 20, "conditions": [{"kind": "burn", "area": "arm", "severity": 20}]}, 0)
    gear.advance(burnt, 11 * 60_000, 0)
    assert any(c["kind"] == "infection" for c in burnt["conditions"])
    health = burnt["health"]
    gear.advance(burnt, 10 * 60_000, 11 * 60_000)
    assert burnt["health"] < health  # No healing, and the infection drains.
    poultice = thing("plantain poultice", ["plantain"], 0.1, None, (), "poultice", "remedy")
    infection = next(i for i, c in enumerate(burnt["conditions"]) if c["kind"] == "infection")
    assert gear.treat(burnt, infection, poultice, 0)["ok"]
    dressing = thing("linen dressing", ["linen"], 0.1, None, ("flexible",), "burn_dressing", "remedy")
    assert gear.treat(burnt, 0, dressing, 0)["ok"]
    assert not gear.untreated(burnt)


def test_a_broken_arm_is_useless_until_splinted():
    state = {"objects": {}}
    victim = person(state)
    sledge = thing("sledge", ["iron", "wood"], 6.0, 1.0, ("rigid",), "sledge")
    gear.apply(victim, gear.hit(state, victim, gear.weapon(sledge), area="arm"), 0)
    assert gear.limb_useless(victim, "arm")
    splint = thing("splint", ["wood", "cord"], 0.4, 0.4, ("rigid",), "splint", "remedy")
    index = next(i for i, c in enumerate(victim["conditions"]) if c["kind"] == "broken")
    gear.treat(victim, index, splint, 0)
    assert not gear.limb_useless(victim, "arm")


def test_a_judged_class_that_does_not_fit_the_thing_is_replaced_by_codes_reading():
    stick = thing("pointed stick", ["wood"], 0.4, 0.9, ("rigid", "sharp_edge"))
    notes = []
    record = gear.checked({"kind": "weapon", "class": "long_sword", "covers": [], "quality": "good"}, stick, notes)
    assert record["class"] != "long_sword" and notes  # A sword needs a hard sharp edge.
    assert (
        gear.checked({"kind": "weapon", "class": "stake", "covers": [], "quality": "fair"}, stick)["class"] == "stake"
    )
    assert gear.classify({"name": "rock", "materials": ["stone"], "mass_kg": 1.5, "flags": ["rigid"]})["class"] in (
        "hand_stone",
        "club",
    )


def test_two_hands_or_one_and_the_player_is_told_what_was_let_go():
    """D-57: a staff takes both hands, so a shield can't go with it; a one-handed weapon and a shield can. Whatever
    has to be let go of is named, with the reason, instead of silently vanishing from a hand."""
    staff = thing("practice staff", ["wood"], 1.5, 1.8, ("rigid",), "staff", oid="staff")
    stick = thing("practice sword", ["wood"], 0.9, 0.9, ("rigid",), "club", oid="stick")
    shield = thing("wicker shield", ["willow"], 2.0, None, ("rigid",), "improvised", "shield", oid="shield")
    state = {"objects": {o["id"]: {**o, "holder_id": "player"} for o in (staff, stick, shield)}}
    me = {"id": "player", "alive": True, "equipped": {}}
    assert gear.equip(state, me, state["objects"]["staff"], "right")["ok"]
    held = gear.equip(state, me, state["objects"]["shield"], "left")
    assert (
        held["ok"] and "The practice staff goes back in your pack: the practice staff takes both hands." in held["text"]
    )
    assert me["equipped"] == {"left": "shield"}
    both = gear.equip(state, me, state["objects"]["staff"], "right")
    assert "The wicker shield goes back in your pack: the practice staff takes both hands." in both["text"]
    assert gear.equip(state, me, state["objects"]["stick"], "right")["ok"]
    assert gear.equip(state, me, state["objects"]["shield"], "left")["ok"]
    assert me["equipped"] == {"right": "stick", "left": "shield"}  # One hand each.
