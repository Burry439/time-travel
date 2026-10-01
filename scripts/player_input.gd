extends Node
## The stranger's hands on the world: keys, clicks, E on the nearest thing, the mouse wheel.

var game: Node2D # The game (scripts/main.gd), whose child this is.


var nearby_target := "" # The nearest thing, for E.


## Nameplates fade in as you come close (or hover); the nearest thing is what E acts on.
func update_nearby() -> void:
	if game.run_state.is_empty():
		return
	var hovered := str(game.ui.cursor.hover.get("id", ""))
	var best := ""
	var best_distance := 90.0
	for id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state.objects[id]
		if obj.holder_id != null or str(obj.get("condition", "usable")) != "usable" or obj.has("scene_node"):
			continue
		var distance: float = game.player.position.distance_to(game.cell_center(int(obj.x), int(obj.y)))
		if distance < best_distance:
			best_distance = distance
			best = str(id)
	for npc in game.run_state.npcs:
		var npc_actor := game.get_node_or_null("NPCs/" + str(npc.id)) as Node2D
		var npc_position: Vector2 = npc_actor.position if npc_actor else game.cell_center(int(npc.x), int(npc.y))
		var distance: float = game.player.position.distance_to(npc_position)
		if distance < best_distance:
			best_distance = distance
			best = str(npc.id)
		var plate := game.get_node_or_null("NPCs/" + str(npc.id) + "/Nameplate") as Label
		if plate:
			plate.modulate.a = 1.0 if hovered == str(npc.id) else clampf((240 - distance) / 90, 0, 1)
	nearby_target = best
	var row: float = game.player.position.y / game.CELL # Where you are, in the map's own words (data/maps).
	var area := str(game.map_plan.get("name", ""))
	for band in game.map_plan.get("areas", []):
		if row < float(band.until_row):
			area = str(band.name)
			break
	game.ui.hud.area.text = area.to_upper()


## E: act on whatever is nearest, as a left click on it would.
func _interact() -> void:
	if nearby_target.is_empty() or game.request_busy:
		return
	left_click(game.ui.cursor.describe(nearby_target))


## Left click in the world: talk to a person, pick up (or steal) a thing, or point at anything else
## in the dialogue bar. With words already in the line (or face to face), clicking points instead.
func left_click(hover: Dictionary) -> void:
	if game.request_busy or not game.gameplay_active:
		return
	if hover.is_empty():
		if game.ui.bar.visible and not game.ui.bar.showing_encounter() and game.ui.bar.line.text.strip_edges().is_empty():
			game.ui.bar.close()
		return
	var id := str(hover.id)
	if not hover.get("reachable", true):
		game.ui.notify("%s is too far away. Walk closer." % str(hover.name).capitalize())
		return
	game.ui.hud.dismiss_hint("controls")
	if game.ui.bar.visible and (game.ui.bar.showing_encounter() or not game.ui.bar.line.text.strip_edges().is_empty()):
		if hover.kind == "person" and hover.action == "talk":
			game.ui.bar.address(id)
		else:
			game.ui.bar.add_reference(id)
		return
	match str(hover.action):
		"talk":
			game.ui.bar.open(id)
		"take":
			game.ui.bar.close()
			game.actions.quick_action("take", id)
		"look":
			game.ui.card.show_for(id)
		_:
			game.ui.bar.open(id)


func _unhandled_input(event: InputEvent) -> void:
	if game.run_state.is_empty():
		return
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP or event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			if game.gameplay_active and not game.ui.modal.visible:
				game.camera_zoom = clampf(game.camera_zoom + (0.05 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -0.05), 0.75, 1.25)
				game.save_settings()
			return
		if not game.gameplay_active or game.ui.modal.visible or game.menu.visible:
			return
		var hover: Dictionary = game.ui.cursor.pick(game.get_global_mouse_position())
		if event.button_index == MOUSE_BUTTON_LEFT:
			left_click(hover)
		elif event.button_index == MOUSE_BUTTON_RIGHT and not hover.is_empty():
			game.ui.card.show_for(str(hover.id))
		get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and not event.pressed and event.keycode == KEY_F and game.fight.guarding:
		game.fight.guard(false) # Let go of F: the shield comes down.
		get_viewport().set_input_as_handled()
		return
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	var hands_free: bool = game.gameplay_active and not game.request_busy and not game.ui.modal.visible and not game.ui.bar.visible
	match event.keycode:
		KEY_ESCAPE:
			if game.ui.card.visible:
				game.ui.card.hide()
			elif game.ui.modal.visible:
				game.ui.close_modal()
			elif game.ui.bar.visible:
				game.ui.bar.escape()
			else:
				game.ui.screens.open_menu()
		KEY_F3:
			if game.run_state.mode == "developer":
				game.trace_panel.visible = not game.trace_panel.visible
		KEY_F4:
			if game.run_state.mode == "developer" and not game.ui.modal.visible:
				game.open_traces()
		KEY_J:
			if game.ui.modal_kind == "journal":
				game.ui.close_modal()
			elif game.gameplay_active:
				game.ui.open_journal()
		KEY_I:
			if game.ui.modal_kind == "inventory":
				game.ui.close_modal()
			elif game.gameplay_active:
				game.ui.pack.open()
		KEY_E:
			if game.gameplay_active and not game.ui.modal.visible and not game.ui.bar.visible:
				_interact()
		KEY_SPACE:
			if hands_free:
				game.fight.strike("right") # Whatever is in the right hand: a blow, a shot, a pour (D-49).
			else:
				return
		KEY_F:
			if not hands_free:
				return
			if not game.fight.shield_hand().is_empty():
				game.fight.guard(true) # Held: the shield stays up until F is let go.
			else:
				game.fight.strike("left")
		KEY_X:
			if hands_free:
				game.fight.swap()
			else:
				return
		KEY_H:
			if game.gameplay_active and not game.ui.modal.visible and not game.ui.bar.visible and game.ui.guide.active():
				game.ui.guide.open_help() # In the tutorial: the step's help, as cards (D-52).
			elif game.gameplay_active and not game.ui.modal.visible and not game.ui.bar.visible:
				game.ui.device.open_ask() # Ask the device (D-50).
			else:
				return
		KEY_Q:
			if hands_free:
				game.fight.strike("right", true) # Throw what's in the right hand.
			else:
				return
		KEY_T, KEY_ENTER, KEY_KP_ENTER:
			if game.gameplay_active and not game.ui.modal.visible:
				game.ui.bar.open()
		_:
			return
	get_viewport().set_input_as_handled()
