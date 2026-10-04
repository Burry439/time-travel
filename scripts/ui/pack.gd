extends Node
## Pack & gear (D-49): what the stranger holds and wears, what they carry, and their body's conditions
## with what treats them.

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var ui: Control # The UI (scripts/game_ui.gd), whose child this is.
var game: Node2D


var gear_note := "" # What equipping something let go of (a two-handed grip), shown atop Pack & gear (D-57).


## Everything you carry, when there's more than the pack bar shows (I).
const SLOT_WORDS := {"right": "Right hand", "left": "Left hand", "head": "Head", "body": "Body", "arms": "Arms",
	"legs": "Legs", "hands": "Hands", "feet": "Feet", "ammo": "Quiver"}


const BODY_SLOTS := ["head", "body", "arms", "legs", "hands", "feet"]


## Pack & gear (D-49): what you hold and wear, what you carry, and your body's conditions with what treats them.
func open() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body: VBoxContainer = ui.begin_modal("Pack & gear", "inventory", Vector2(760, 620))
	ui.guide.report("pack")
	if not gear_note.is_empty(): # What the last change let go of, and why (D-57): never silently.
		var note: Label = ui.label(gear_note, 15)
		note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		note.add_theme_color_override("font_color", ui.UITheme.ACCENT)
		note.add_theme_font_override("font", ui.UITheme.serif(false, true))
		body.add_child(note)
		gear_note = ""
	var player: Dictionary = game.run_state.get("player", {})
	var carried: Array[Dictionary] = ui.hud.carried_objects()
	var conditions: Array = player.get("conditions", []) if typeof(player.get("conditions")) == TYPE_ARRAY else []
	if not conditions.is_empty():
		body.add_child(_section("Your body"))
		for index in conditions.size():
			var condition: Dictionary = conditions[index]
			if str(condition.get("kind", "")) == "knocked_out":
				continue
			var row := HBoxContainer.new()
			row.add_theme_constant_override("separation", 8)
			body.add_child(row)
			var words: Label = ui.label(condition_words(condition), 16)
			words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			words.add_theme_color_override("font_color", ui.UITheme.BAD if _needs_treating(condition) else ui.UITheme.INK_SOFT)
			row.add_child(words)
			if not _needs_treating(condition):
				continue
			var fits := carried.filter(func(o: Dictionary) -> bool: return _treats(o, str(condition.kind)))
			if fits.is_empty():
				row.add_child(ui.label("Nothing to treat it with", 14))
			for remedy in fits.slice(0, 3):
				var rid := str(remedy.id)
				var i := int(index)
				row.add_child(ui.button("Treat with the " + str(remedy.name), func() -> void:
					var result: Dictionary = await game.fight.treat(rid, i)
					ui.notify(str(result.get("text", result.get("reason", ""))))
					open(), "Chip"))
	body.add_child(_section("Holding and wearing"))
	var worn_ids := {}
	var shown := 0
	for slot in SLOT_WORDS:
		var obj: Dictionary = game.fight.in_hand(player, slot)
		if obj.is_empty():
			continue
		worn_ids[str(obj.id)] = true
		if slot == "left" and str(game.fight.in_hand(player, "right").get("id", "")) == str(obj.id):
			continue # Two hands on one thing: shown once.
		shown += 1
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		body.add_child(row)
		row.add_child(ui.object_icon(obj, 48))
		var words: Label = ui.label("%s: %s\n%s" % [SLOT_WORDS[slot], str(obj.name), gear_words(obj)], 15)
		words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(words)
		var id := str(obj.id)
		if obj.get("readable") != null: # A book in hand: read it (D-55).
			row.add_child(ui.button("Read", ui.open_book.bind(obj), "Chip"))
		row.add_child(ui.button("Take off" if slot in BODY_SLOTS else "Put away", func() -> void:
			var result: Dictionary = await game.fight.equip(id, "")
			if not result.get("ok", false):
				ui.notify(str(result.get("reason", "")))
			open(), "Chip"))

	if shown == 0:
		ui.small(body, "Empty-handed. Space and F use what's in your right and left hands; X swaps them.")
	body.add_child(_section("In your pack"))
	var loose := carried.filter(func(o: Dictionary) -> bool: return not worn_ids.has(str(o.id)))
	if loose.is_empty():
		ui.paragraph(body, "Nothing else.\n\nClick a loose thing in the world to pick it up. What might you make with what you find?")
	for obj in loose:
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 8)
		body.add_child(row)
		row.add_child(ui.object_icon(obj, 48))
		var made := "  ·  made by you" if obj.get("created_by") == "player" else ""
		var words: Label = ui.label(str(obj.name).capitalize() + "  ·  " + str(obj.mass_kg) + " kg" + made + "\n" + gear_words(obj), 15)
		words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(words)
		var id := str(obj.id)
		if obj.get("readable") != null:
			row.add_child(ui.button("Read", ui.open_book.bind(obj), "Chip"))
		for slot in _slots_for(obj):
			var chosen := str(slot)
			var verb := "Wear" if chosen in BODY_SLOTS else "Ready" if chosen == "ammo" else "Right hand" if chosen == "right" else "Left hand"
			row.add_child(ui.button(verb, func() -> void:
				var result: Dictionary = await game.fight.equip(id, chosen)
				if not result.get("ok", false):
					ui.notify(str(result.get("reason", "")))
				elif "goes back in your pack" in str(result.get("text", "")):
					gear_note = str(result.text)
				if result.get("ok", false) and obj.get("readable") != null and chosen in ["right", "left"]:
					ui.open_book(game.run_state.objects.get(id, obj)) # A book taken in hand opens (D-55).
					return
				open(), "Chip"))
		row.add_child(ui.button("Use…", func() -> void:
			ui.close_modal()
			ui.bar.open(id), "Chip"))
		row.add_child(ui.button("Put down", game.actions.quick_action.bind("drop", id), "Chip"))


func _section(text: String) -> Label:
	var node: Label = ui.label(text, 19)
	node.add_theme_font_override("font", ui.UITheme.serif(true))
	node.add_theme_color_override("font_color", ui.UITheme.INK)
	return node


## Where a thing can go: worn things where they cover, ammunition in the quiver, anything else in a hand.
func _slots_for(obj: Dictionary) -> Array:
	var record = obj.get("gear")
	if typeof(record) == TYPE_DICTIONARY:
		match str(record.get("kind", "")):
			"armour", "clothing":
				var covers: Array = record.get("covers", [])
				return covers.filter(func(c) -> bool: return c in BODY_SLOTS).slice(0, 1)
			"ammo":
				return ["ammo"]
			"remedy":
				return []
	return ["right", "left"]


## How a thing strikes someone who handles it, in plain words (numbers only in developer mode).
func gear_words(obj: Dictionary) -> String:
	var record = obj.get("gear")
	if typeof(record) != TYPE_DICTIONARY:
		return ""
	var table: Dictionary = game.fight.table
	var kind := str(record.get("kind", ""))
	var cls := str(record.get("class", ""))
	if kind == "weapon" and table.get("weapons", {}).has(cls):
		var spec: Dictionary = table.weapons[cls]
		var base := float(spec.get("base", 0))
		var level := "Deadly" if base >= 45 else "Dangerous" if base >= 28 else "Painful" if base >= 12 else "Feeble"
		var how: String = {"cut": "cuts", "pierce": "stabs", "blunt": "clubs", "burn": "burns"}.get(str(spec.type), "hits")
		var reach := "shoots far" if spec.has("range") else "reaches far" if float(spec.reach) >= 2.2 else "close work"
		var dev := "  [%s: %d, reach %.1f, wind-up %d ms]" % [cls, int(base), float(spec.reach), int(spec.windup_ms)] \
			if game.run_state.get("mode", "") == "developer" else ""
		return "%s %s: %s, %s, %s.%s" % [level, spec.name, how, reach, "two hands" if int(spec.hands) == 2 else "one hand", dev]
	if kind in ["armour", "clothing"] and table.get("armour", {}).has(cls):
		var spec: Dictionary = table.armour[cls]
		var cuts := "stops cuts well" if float(spec.cut) >= 0.8 else "turns some cuts" if float(spec.cut) >= 0.35 else "little against a blade"
		var blows := "blunt blows still get through" if float(spec.blunt) < 0.4 else "softens blows"
		return "%s: %s; %s." % [str(spec.name).capitalize(), cuts, blows]
	if kind == "shield":
		return "A shield: hold its key to raise it against blows from the front."
	if kind == "remedy" and table.get("remedies", {}).has(cls):
		return "Treats %s." % ", ".join(PackedStringArray(table.remedies[cls].treats.keys()))
	if kind == "ammo":
		return "%d left." % int(obj.get("count", 1))
	return ""


func condition_words(condition: Dictionary) -> String:
	var areas := {"arm": "arm", "leg": "leg", "head": "head", "neck": "neck", "heart": "chest", "torso": "side"}
	var area: String = areas.get(str(condition.get("area", "torso")), "side")
	var treated := int(condition.get("treated", 0))
	match str(condition.kind):
		"bleeding":
			if not _needs_treating(condition):
				return "A cut on your %s, bound (%s)." % [area, str(condition.get("treated_with", "treated"))]
			return ("A deep cut on your %s is bleeding badly." if condition.get("heavy", false) else "A cut on your %s is bleeding.") % area \
				+ (" It's only slowed." if treated > 0 else "")
		"burn":
			return "A burn on your %s%s." % [area, ", dressed" if treated > 0 else " (it will fester if left)"]
		"broken":
			return "Your %s is broken%s." % [area, ", splinted" if treated >= 2 else ": it can't take any weight or grip"]
		"infection":
			return "The wound on your %s is festering%s." % [area, ", poulticed" if treated > 0 else ": it's making you ill"]
		"ache":
			return "Your %s aches%s." % ["knees" if area == "leg" else area, ", eased" if treated > 0 else ""]
	return str(condition.kind)


func _needs_treating(condition: Dictionary) -> bool:
	var treated := int(condition.get("treated", 0))
	match str(condition.get("kind", "")):
		"bleeding":
			return not (treated >= 3 or treated == 2 or (treated >= 1 and not condition.get("heavy", false)))
		"burn", "infection", "broken":
			return treated == 0
	return false


func _treats(obj: Dictionary, kind: String) -> bool:
	var record = obj.get("gear")
	if typeof(record) != TYPE_DICTIONARY or str(record.get("kind", "")) != "remedy":
		return false
	var remedy: Dictionary = game.fight.table.get("remedies", {}).get(str(record.get("class", "")), {})
	return remedy.get("treats", {}).has(kind)

