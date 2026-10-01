extends Control
## The journal's map, drawn in ink on parchment from data/maps/village.json. Only places you have
## walked near are revealed (fog of war, remembered per journey). People you've met show where you
## last saw them; open leads get a small red mark on the person they point to. Nothing is marked in
## the world itself.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const CELLS := Vector2(96, 72)
const BLOCK := 4 # Fog is revealed in 4×4-cell blocks.
const LABELS := {"Smithy": "Smithy", "Inn": "The Wayside Inn", "Carpenter": "Carpenter's yard",
	"Wagon": "Merchant's wagon", "EastWorkshop": "Workshop", "SouthHouse": "House"}

var ui: Control
var game: Node2D
var geometry: Dictionary = {}
var font: Font = UITheme.serif(true) # Held here: a font freed mid-frame draws as black boxes.
var small: Font = UITheme.serif(false, true)


func setup(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	var parsed = JSON.parse_string(FileAccess.get_file_as_string("res://data/maps/village.json"))
	geometry = parsed if typeof(parsed) == TYPE_DICTIONARY else {"buildings": [], "obstacles": []}
	custom_minimum_size = Vector2(640, 440)
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _scale() -> float:
	return minf(size.x / CELLS.x, size.y / CELLS.y)


func _origin() -> Vector2:
	return (size - CELLS * _scale()) * 0.5


func to_map(cell: Vector2) -> Vector2:
	return _origin() + cell * _scale()


func revealed(cell: Vector2i) -> bool:
	return ui.visited.has(Vector2i(cell.x / BLOCK, cell.y / BLOCK))


func _draw() -> void:
	var s := _scale()
	var area := Rect2(_origin(), CELLS * s)
	var ink := Color(UITheme.INK, 0.85)
	draw_texture_rect(UITheme.texture("map_paper"), area, true)
	# The road north to the gate, and the wall.
	var road := PackedVector2Array()
	for y in range(71, 8, -1):
		road.append(to_map(Vector2(48.5 + sin(y * 0.21) * 0.9, y)))
	draw_polyline(road, Color(0.62, 0.48, 0.30, 0.55), s * 3.2, true)
	draw_rect(Rect2(to_map(Vector2(0, 7)), Vector2(46, 2) * s), Color(0.35, 0.27, 0.18, 0.9))
	draw_rect(Rect2(to_map(Vector2(51, 7)), Vector2(45, 2) * s), Color(0.35, 0.27, 0.18, 0.9))
	var gate_open: bool = game.run_state.get("gate_open", false)
	draw_rect(Rect2(to_map(Vector2(46, 7)), Vector2(5, 2) * s), Color(0.55, 0.34, 0.16, 0.9) if not gate_open
		else Color(0.9, 0.8, 0.5, 0.4))
	_label(font, "THE CITY", to_map(Vector2(48.5, 4.5)), 16, ink)
	_label(small, "the gate", to_map(Vector2(48.5, 10.8)), 12, ink)
	var cleared := {}
	for obj in game.run_state.get("objects", {}).values():
		if obj.has("geometry_name") and str(obj.get("condition", "usable")) != "usable":
			cleared[str(obj.geometry_name)] = true
	for item in geometry.get("buildings", []):
		var c: Array = item.cells
		var rect := Rect2(to_map(Vector2(c[0], c[1])), Vector2(c[2], c[3]) * s)
		draw_rect(rect, Color(0.55, 0.40, 0.24, 0.35))
		for i in range(0, int(rect.size.x), 6): # Hatching.
			var end := Vector2(minf(i + rect.size.y, rect.size.x), maxf(0, rect.size.y - (rect.size.x - i)))
			draw_line(rect.position + Vector2(i, rect.size.y), rect.position + end, Color(ink, 0.25), 1.0)
		draw_rect(rect, ink, false, 1.5)
		_label(font, str(LABELS.get(str(item.name), item.name)), rect.get_center() + Vector2(0, rect.size.y * 0.5 + 12), 13, ink)
	for item in geometry.get("obstacles", []):
		if str(item.name) in cleared or not str(item.name).begins_with("Tree"):
			continue
		var at := to_map(Vector2(item.cells[0] + 0.5, item.cells[1] + 0.5))
		draw_circle(at, s * 1.4, Color(0.30, 0.42, 0.22, 0.55))
		draw_arc(at, s * 1.4, 0, TAU, 16, Color(ink, 0.6), 1.0, true)
	# Fog over everything not yet walked near.
	var fog := Color(UITheme.PARCHMENT_DARK.lerp(UITheme.PARCHMENT, 0.4), 0.93)
	for by in range(0, int(CELLS.y) / BLOCK):
		for bx in range(0, int(CELLS.x) / BLOCK):
			if not ui.visited.has(Vector2i(bx, by)):
				draw_rect(Rect2(to_map(Vector2(bx, by) * BLOCK) - Vector2(0.5, 0.5), Vector2.ONE * BLOCK * s + Vector2.ONE), fog)
	# Leads point at people: a red ring on each.
	var pointed := {}
	var learned: Array = game.run_state.get("learned", [])
	for index in learned.size():
		var claim: Dictionary = learned[index]
		if ui.lead_done(index):
			continue
		for key in ["refer", "npc_id"]:
			if claim.has(key) and (key == "refer" or claim.has("offer") or claim.has("lend")):
				pointed[str(claim[key])] = true
	for npc in game.run_state.get("npcs", []):
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		var met: bool = their_mind.get("met", false)
		if not met and not pointed.has(str(npc.id)):
			continue
		var at := to_map(Vector2(int(npc.x) + 0.5, int(npc.y) + 0.5))
		if pointed.has(str(npc.id)):
			draw_arc(at, 9, 0, TAU, 20, UITheme.STEAL, 2.0, true)
		if met:
			draw_circle(at, 4, UITheme.ACCENT if npc.get("alive", true) else Color(0.4, 0.4, 0.4))
			_label(small, str(npc.name), at + Vector2(0, -8), 12, ink)
	# You.
	var you := to_map(Vector2(game.predicted_cell) + Vector2(0.5, 0.5))
	var arrow := PackedVector2Array([you + Vector2(0, -8), you + Vector2(6, 6), you + Vector2(0, 3), you + Vector2(-6, 6)])
	draw_colored_polygon(arrow, UITheme.GOLD)
	draw_polyline(arrow + PackedVector2Array([arrow[0]]), UITheme.INK, 1.5, true)
	_label(font, "You", you + Vector2(0, 20), 12, UITheme.INK)
	draw_rect(area, ink, false, 2.0)


func _label(font: Font, text: String, centre: Vector2, font_size: int, colour: Color) -> void:
	var width := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x
	draw_string(font, centre - Vector2(width * 0.5, 0), text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size, colour)
