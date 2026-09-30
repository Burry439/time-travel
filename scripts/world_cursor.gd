extends Node
## What is under the mouse in the world, and what a click would do (GDD D-35).
## People are picked by their painted body, loose things by their sprite, map trees by their trunk.
## The hover drives the tooltip, the cursor badge, the gold ring and a slight brighten.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
## About 14 steps of walking plus arm's reach (backend crafting.NEARBY_WALK_STEPS, m2.REACH_CELLS).
const REACH_CELLS := 16.0

var game: Node2D
var ui: Control
var hover: Dictionary = {}
var _cursor_kind := ""
var _lit: CanvasItem = null
var _lit_was := Color.WHITE
var _hardware_cursor := DisplayServer.get_name() != "headless"


func _process(_delta: float) -> void:
	var next: Dictionary = {}
	if _can_hover():
		next = pick(game.get_global_mouse_position())
	_highlight(next)
	hover = next
	var dragged: String = ui.hud.dragging
	if not dragged.is_empty() and not ui.pointer_over_ui():
		var phrase: String = ui.drop_phrase(dragged, next)
		ui.hud.show_tip(phrase, "Let go to write it in the line", "")
		_set_cursor("use")
	elif next.is_empty():
		ui.hud.hide_tip()
		_set_cursor("arrow")
	else:
		ui.hud.show_tip(str(next.verb), str(next.note), str(next.tone))
		_set_cursor(str(next.cursor))
	game.effects.has_target = not next.is_empty()
	if not next.is_empty():
		game.effects.marker = next.at


func _can_hover() -> bool:
	return game.gameplay_active and not game.run_state.is_empty() and not ui.modal.visible \
		and not game.menu.visible and not ui.pointer_over_ui()


func _set_cursor(kind: String) -> void:
	if kind == _cursor_kind:
		return
	_cursor_kind = kind
	if _hardware_cursor:
		Input.set_custom_mouse_cursor(UITheme.cursor(kind), Input.CURSOR_ARROW, Vector2(2, 2))


func cursor_kind() -> String:
	return _cursor_kind


## The most specific thing under a world position: people first, then the smallest thing hit.
func pick(at: Vector2) -> Dictionary:
	var best_id := ""
	var best_score := INF
	for npc in game.run_state.get("npcs", []):
		var actor := game.get_node_or_null("NPCs/" + str(npc.id)) as Node2D
		if actor == null:
			continue
		var box := Rect2(actor.position + Vector2(-24, -104), Vector2(48, 110)) if npc.get("alive", true) \
			else Rect2(actor.position + Vector2(-52, -34), Vector2(104, 44))
		if box.has_point(at):
			var score := box.get_area() * 0.4 + at.distance_to(box.get_center())
			if score < best_score:
				best_score = score
				best_id = str(npc.id)
	for id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state.objects[id]
		if obj.get("holder_id") != null:
			continue
		var box := object_box(obj)
		if box.has_area() and box.has_point(at):
			var score := box.get_area() + at.distance_to(box.get_center())
			if score < best_score:
				best_score = score
				best_id = str(id)
	return {} if best_id.is_empty() else describe(best_id)


## Where an object is drawn in the world (empty if it isn't shown).
func object_box(obj: Dictionary) -> Rect2:
	var node: CanvasItem = null
	if obj.has("scene_node"):
		node = game.get_node_or_null(str(obj.scene_node)) as CanvasItem
	else:
		node = game.get_node_or_null("M2Objects/" + str(obj.id)) as CanvasItem
	if node == null or not node.is_visible_in_tree():
		return Rect2()
	var sprite := node as Sprite2D
	if sprite and sprite.texture:
		var box: Rect2 = sprite.global_transform * sprite.get_rect()
		if str(obj.get("feature", "")) == "tree": # The trunk and lower crown, not the whole canopy.
			return Rect2(box.position.x + box.size.x * 0.3, box.position.y + box.size.y * 0.3,
				box.size.x * 0.4, box.size.y * 0.7)
		return box.grow(4)
	var at: Vector2 = (node as Node2D).global_position if node is Node2D else game._cell_center(int(obj.x), int(obj.y))
	return Rect2(at - Vector2(24, 30), Vector2(48, 48))


## A hover for a person or thing: its name, what left-click does, and whether it's within reach.
func describe(id: String) -> Dictionary:
	var here := Vector2(game.predicted_cell)
	var npc: Dictionary = ui.npc_record(id)
	var result := {"id": id, "note": "Right-click to look closer", "tone": ""}
	var cell: Vector2
	if not npc.is_empty():
		var actor := game.get_node_or_null("NPCs/" + id) as Node2D
		cell = Vector2(int(npc.x), int(npc.y))
		var spot: Vector2 = actor.position if actor else game._cell_center(int(cell.x), int(cell.y))
		result.merge({"kind": "person", "name": str(npc.name), "at": spot}, true)
		if npc.get("alive", true):
			result.merge({"verb": "Talk to " + str(npc.name), "action": "talk", "cursor": "talk"}, true)
		else:
			result.merge({"verb": str(npc.name) + " (dead)", "action": "look", "cursor": "look", "tone": "dead",
				"note": "Left-click to look closer"}, true)
	else:
		var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
		if obj.is_empty():
			return {}
		cell = Vector2(int(obj.x), int(obj.y))
		var name := str(obj.name)
		result.merge({"kind": "object", "name": name, "at": game._cell_center(int(cell.x), int(cell.y))}, true)
		var owner: String = game.owner_name(obj)
		var theirs: bool = obj.get("owner_id") != null and obj.owner_id != "player" and obj.get("lent_to") != "player"
		if "carry" in obj.get("capabilities", []) and str(obj.get("condition", "usable")) == "usable":
			if theirs:
				result.merge({"verb": "Steal %s's %s" % [owner, name], "action": "take", "cursor": "steal", "tone": "steal",
					"note": "It isn't yours  ·  Right-click to look closer"}, true)
			else:
				result.merge({"verb": "Pick up the " + name, "action": "take", "cursor": "take"}, true)
		else:
			result.merge({"verb": "Use the " + name, "action": "use", "cursor": "use"}, true)
			if theirs:
				result.note = "%s's  ·  Right-click to look closer" % owner
	result["reachable"] = here.distance_to(cell) <= REACH_CELLS
	if not result.reachable:
		result.merge({"tone": "far", "cursor": "far", "note": "Too far away  ·  walk closer"}, true)
		result.verb = str(result.name)
	return result


func _highlight(next: Dictionary) -> void:
	var node: CanvasItem = null
	if not next.is_empty():
		node = game.get_node_or_null("NPCs/%s/PaintedActor" % next.id) as CanvasItem
		if node == null:
			var obj: Dictionary = game.run_state.get("objects", {}).get(str(next.id), {})
			node = game.get_node_or_null(str(obj.get("scene_node", "M2Objects/" + str(next.id)))) as CanvasItem
	if node == _lit:
		return
	if is_instance_valid(_lit):
		_lit.modulate = _lit_was
	_lit = node
	if node:
		_lit_was = node.modulate
		node.modulate = Color(_lit_was.r * 1.18, _lit_was.g * 1.16, _lit_was.b * 1.08, _lit_was.a)
