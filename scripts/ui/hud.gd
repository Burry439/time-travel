extends Control
## Always on screen while playing: where you are and what you're after, Journal and Menu, the
## inventory bar (drag things out of it onto people and things), your condition, notices, and the
## hover tooltip for whatever is under the mouse.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const SLOTS := 10

var ui: Control
var game: Node2D
var area: Label
var status: Label
var slots_box: HBoxContainer
var weight: Label
var inventory: PanelContainer
var objective: PanelContainer
var corner: HBoxContainer
var condition_box: VBoxContainer
var notices: VBoxContainer
var history: Array[Dictionary] = [] # Every notice this session, for the journal.
var tip: PanelContainer
var tip_title: Label
var tip_note: Label
var hint_card: PanelContainer
var drag_icon: TextureRect
var press_id := ""
var press_at := Vector2.ZERO
var dragging := ""
var _signature := ""


class Star extends Control:
	func _draw() -> void:
		var c := size * 0.5
		var points := PackedVector2Array()
		for i in 8:
			var radius := 5.5 if i % 2 == 0 else 2.0
			points.append(c + Vector2.from_angle(i * PI / 4.0 - PI / 2.0) * radius)
		draw_colored_polygon(points, Color("f0cf86"))
		draw_polyline(points + PackedVector2Array([points[0]]), Color("3a250f"), 1.0, true)


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE

	objective = PanelContainer.new()
	objective.theme_type_variation = "WoodPanel"
	objective.position = Vector2(16, 14)
	objective.custom_minimum_size = Vector2(310, 0)
	objective.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(objective)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 0)
	objective.add_child(column)
	area = _wood_label("THE SOUTH ROAD", 12, UITheme.GOLD)
	area.add_theme_font_override("font", UITheme.serif(true))
	column.add_child(area)
	var goal := _wood_label("Find a way into the city", 20)
	goal.add_theme_font_override("font", UITheme.serif(true))
	column.add_child(goal)
	status = _wood_label("", 13, Color(UITheme.CREAM, 0.8))
	column.add_child(status)

	corner = HBoxContainer.new()
	corner.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	corner.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	corner.offset_right = -16
	corner.offset_top = 14
	corner.add_theme_constant_override("separation", 8)
	add_child(corner)
	corner.add_child(ui.button("Journal  ·  J", func() -> void: ui.open_journal()))
	corner.add_child(ui.button("Menu  ·  Esc", func() -> void: ui.open_menu()))

	inventory = PanelContainer.new()
	inventory.theme_type_variation = "WoodPanel"
	inventory.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	inventory.grow_horizontal = Control.GROW_DIRECTION_BOTH
	inventory.grow_vertical = Control.GROW_DIRECTION_BEGIN
	inventory.offset_bottom = -10
	add_child(inventory)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	inventory.add_child(row)
	slots_box = HBoxContainer.new()
	slots_box.add_theme_constant_override("separation", 5)
	row.add_child(slots_box)
	var side := VBoxContainer.new()
	side.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(side)
	var pack := _wood_label("PACK  ·  I", 11, UITheme.GOLD)
	pack.add_theme_font_override("font", UITheme.serif(true))
	side.add_child(pack)
	weight = _wood_label("0 / 20 kg", 14)
	side.add_child(weight)

	condition_box = VBoxContainer.new()
	condition_box.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	condition_box.grow_vertical = Control.GROW_DIRECTION_BEGIN
	condition_box.offset_left = 16
	condition_box.offset_bottom = -14
	condition_box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(condition_box)

	notices = VBoxContainer.new()
	notices.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	notices.grow_horizontal = Control.GROW_DIRECTION_BOTH
	notices.offset_top = 16
	notices.custom_minimum_size.x = 520
	notices.offset_left = -260
	notices.offset_right = 260
	notices.mouse_filter = Control.MOUSE_FILTER_IGNORE
	notices.add_theme_constant_override("separation", 6)
	add_child(notices)

	hint_card = PanelContainer.new()
	hint_card.theme_type_variation = "PaperPanel"
	hint_card.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	hint_card.grow_horizontal = Control.GROW_DIRECTION_BOTH
	hint_card.grow_vertical = Control.GROW_DIRECTION_BEGIN
	hint_card.offset_bottom = -124
	hint_card.hide()
	add_child(hint_card)

	tip = PanelContainer.new()
	tip.theme_type_variation = "PaperPanel"
	tip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tip.top_level = false
	var tip_column := VBoxContainer.new()
	tip_column.add_theme_constant_override("separation", 0)
	tip_column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tip.add_child(tip_column)
	tip_title = Label.new()
	tip_title.add_theme_font_override("font", UITheme.serif(true))
	tip_title.add_theme_font_size_override("font_size", 16)
	tip_column.add_child(tip_title)
	tip_note = Label.new()
	tip_note.theme_type_variation = "Small"
	tip_column.add_child(tip_note)
	tip.hide()
	add_child(tip)

	drag_icon = TextureRect.new()
	drag_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	drag_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	drag_icon.custom_minimum_size = Vector2(46, 46)
	drag_icon.size = Vector2(46, 46)
	drag_icon.modulate.a = 0.85
	drag_icon.mouse_filter = Control.MOUSE_FILTER_IGNORE
	drag_icon.hide()
	add_child(drag_icon)


## Panels the stranger walks behind fade so they never hide him (a safety net for the map's edges).
func _process(delta: float) -> void:
	if game.run_state.is_empty():
		return
	var zoom: float = game.camera.zoom.y
	var feet: Vector2 = game.player.get_global_transform_with_canvas().origin / ui.ui_scale
	var body := Rect2(feet + Vector2(-26, -112) * zoom / ui.ui_scale, Vector2(52, 124) * zoom / ui.ui_scale)
	for panel in [inventory, objective, corner]:
		var over: bool = Rect2(panel.position, panel.size).intersects(body)
		panel.modulate.a = move_toward(panel.modulate.a, 0.3 if over else 1.0, delta * 4.0)


func _wood_label(text: String, font_size: int, colour := UITheme.CREAM) -> Label:
	var node := Label.new()
	node.theme_type_variation = "WoodLabel"
	node.text = text
	node.add_theme_font_size_override("font_size", font_size)
	node.add_theme_color_override("font_color", colour)
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return node


## Called whenever the world state changes; rebuilds the slots only when what you carry changed.
func refresh() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		return
	var leads: int = ui.open_leads().size()
	status.text = ("The city gate is open ↑" if state.get("gate_open", false) else "The gate lies to the north ↑") + \
		("  ·  %d open lead%s" % [leads, "" if leads == 1 else "s"] if leads > 0 else "")
	var carried := carried_objects()
	var mass := 0.0
	var signature := PackedStringArray()
	for obj in carried:
		mass += float(obj.get("mass_kg", 0)) + float(obj.get("water_l", 0))
		signature.append("%s:%s:%s" % [obj.id, game.sprite_status(obj), obj.get("water_l", 0)])
	weight.text = "%s / 20 kg" % String.num(mass, 1) # m2.CARRY_LIMIT_KG
	weight.add_theme_color_override("font_color", UITheme.STEAL.lightened(0.3) if mass > 18.0 else UITheme.CREAM)
	if ",".join(signature) != _signature:
		_signature = ",".join(signature)
		_rebuild_slots(carried)
	for child in condition_box.get_children():
		child.queue_free()
	var player: Dictionary = state.get("player", {})
	var health := float(player.get("health", 100))
	if player.get("alive", true) and health < 100.0:
		_condition("Wounded  ·  %d / 100" % roundi(health), UITheme.BAD)
	var barred := int(state.get("barred_until") if state.get("barred_until") != null else 0) - int(state.get("sim_time_ms", 0))
	if barred > 0:
		_condition("Barred from the gate  ·  about %d min" % maxi(1, ceili(barred / 60000.0)), UITheme.ACCENT)


func _condition(text: String, colour: Color) -> void:
	var chip := PanelContainer.new()
	chip.theme_type_variation = "PaperPanel"
	chip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var words := Label.new()
	words.text = text
	words.add_theme_color_override("font_color", colour)
	words.add_theme_font_override("font", UITheme.serif(true))
	words.add_theme_font_size_override("font_size", 14)
	chip.add_child(words)
	condition_box.add_child(chip)


func carried_objects() -> Array[Dictionary]:
	var carried: Array[Dictionary] = []
	for id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state.objects[id]
		if obj.get("holder_id") == "player":
			carried.append(obj)
	return carried


func _rebuild_slots(carried: Array[Dictionary]) -> void:
	for child in slots_box.get_children():
		slots_box.remove_child(child)
		child.queue_free()
	for index in SLOTS:
		var slot := PanelContainer.new()
		slot.theme_type_variation = "SlotPanel"
		slot.custom_minimum_size = Vector2(54, 54)
		slots_box.add_child(slot)
		if index >= carried.size():
			slot.modulate.a = 0.55
			slot.mouse_filter = Control.MOUSE_FILTER_IGNORE
			continue
		if index == SLOTS - 1 and carried.size() > SLOTS:
			var more := _wood_label("+%d" % (carried.size() - SLOTS + 1), 18, UITheme.GOLD)
			more.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			more.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
			slot.add_child(more)
			slot.tooltip_text = "Everything you carry  (I)"
			slot.gui_input.connect(func(event: InputEvent) -> void:
				if event is InputEventMouseButton and event.pressed:
					ui.open_inventory())
			continue
		var obj: Dictionary = carried[index]
		var icon: TextureRect = ui.object_icon(obj, 48)
		icon.mouse_filter = Control.MOUSE_FILTER_IGNORE
		slot.add_child(icon)
		slot.set_meta("object_id", str(obj.id))
		if obj.get("created_by") == "player":
			var star := Star.new()
			star.custom_minimum_size = Vector2(14, 14)
			star.size_flags_horizontal = Control.SIZE_SHRINK_END
			star.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
			star.mouse_filter = Control.MOUSE_FILTER_IGNORE
			slot.add_child(star)
		var water := ""
		if float(obj.get("capacity_l", 0)) > 0:
			water = "\nWater: %s of %s litres" % [obj.get("water_l", 0), obj.capacity_l]
		slot.tooltip_text = "%s\n%s kg%s%s\nDrag onto someone or something · Right-click to look closer" % [
			str(obj.name).capitalize(), obj.mass_kg, "  ·  made by you" if obj.get("created_by") == "player" else "",
			water]
		slot.gui_input.connect(_slot_input.bind(str(obj.id)))


func slot_ids() -> Array[String]:
	var ids: Array[String] = []
	for slot in slots_box.get_children():
		if slot.has_meta("object_id"):
			ids.append(str(slot.get_meta("object_id")))
	return ids


func _slot_input(event: InputEvent, id: String) -> void:
	if not event is InputEventMouseButton or not event.pressed:
		return
	if event.button_index == MOUSE_BUTTON_RIGHT:
		ui.card.show_for(id, get_global_mouse_position())
		accept_event()
	elif event.button_index == MOUSE_BUTTON_LEFT:
		press_id = id
		press_at = get_global_mouse_position()
		accept_event()


func _input(event: InputEvent) -> void:
	if press_id.is_empty():
		return
	if event is InputEventMouseMotion:
		if dragging.is_empty() and get_global_mouse_position().distance_to(press_at) > 8.0:
			start_drag(press_id)
		if not dragging.is_empty():
			drag_icon.position = get_local_mouse_position() - drag_icon.size * 0.5
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not event.pressed:
		var id := press_id
		press_id = ""
		if dragging.is_empty():
			ui.item_clicked(id)
		else:
			finish_drag()
		get_viewport().set_input_as_handled()


func start_drag(id: String) -> void:
	dragging = id
	press_id = id
	var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
	drag_icon.texture = game.texture_for(obj) if not obj.is_empty() else null
	drag_icon.position = get_local_mouse_position() - drag_icon.size * 0.5
	drag_icon.show()
	ui.sounds.play("click")


## Let go of a dragged item: onto another item, onto the world (a person, a thing, the ground), or nowhere.
func finish_drag() -> void:
	var id := dragging
	dragging = ""
	press_id = ""
	drag_icon.hide()
	for slot in slots_box.get_children():
		if slot.has_meta("object_id") and Rect2(Vector2.ZERO, slot.size).has_point(slot.get_local_mouse_position()):
			if str(slot.get_meta("object_id")) != id:
				ui.drop_on_item(id, str(slot.get_meta("object_id")))
			return
	var over := get_viewport().gui_get_hovered_control()
	if over != null and over != self and not _is_world_passthrough(over):
		return # Dropped on some other panel: nothing happens.
	ui.drop_on_world(id)


func _is_world_passthrough(control: Control) -> bool:
	return control.mouse_filter == Control.MOUSE_FILTER_IGNORE


func notify(text: String) -> void:
	if text.strip_edges().is_empty():
		return
	var clock := int(game.run_state.get("sim_time_ms", 0)) / 1000 if not game.run_state.is_empty() else 0
	if not history.is_empty() and history[-1].text == text and notices.get_child_count() > 0:
		return
	history.append({"text": text, "clock": "%d:%02d" % [clock / 60, clock % 60]})
	while notices.get_child_count() >= 3:
		var oldest := notices.get_child(0)
		notices.remove_child(oldest)
		oldest.queue_free()
	var card := PanelContainer.new()
	card.theme_type_variation = "PaperPanel"
	card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var words := Label.new()
	words.text = text
	words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	words.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	words.custom_minimum_size.x = 480
	words.add_theme_font_size_override("font_size", 15)
	card.add_child(words)
	notices.add_child(card)
	var fade := card.create_tween()
	card.modulate.a = 0.0
	fade.tween_property(card, "modulate:a", 1.0, 0.2)
	fade.tween_interval(4.5)
	fade.tween_property(card, "modulate:a", 0.0, 0.8)
	fade.tween_callback(card.queue_free)


func show_tip(title: String, note: String, tone: String) -> void:
	tip_title.text = title
	tip_note.text = note
	tip_note.visible = not note.is_empty()
	tip_title.add_theme_color_override("font_color", {"steal": UITheme.STEAL, "far": UITheme.INK_SOFT,
		"dead": UITheme.INK_SOFT}.get(tone, UITheme.INK))
	tip.reset_size()
	var at := get_local_mouse_position() + Vector2(20, 24)
	at.x = minf(at.x, size.x - tip.size.x - 8)
	at.y = minf(at.y, size.y - tip.size.y - 8)
	tip.position = at
	tip.show()


func hide_tip() -> void:
	tip.hide()


## A first-time hint, shown once per player (remembered in user://presentation.cfg).
func show_hint(key: String, text: String) -> void:
	if ui.hint_seen(key):
		return
	for child in hint_card.get_children():
		hint_card.remove_child(child)
		child.queue_free()
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	hint_card.add_child(row)
	var words := Label.new()
	words.text = text
	words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	words.custom_minimum_size.x = 560
	words.add_theme_font_size_override("font_size", 15)
	row.add_child(words)
	var ok: Button = ui.button("Got it", func() -> void: dismiss_hint(key), "Chip")
	ok.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(ok)
	hint_card.set_meta("key", key)
	hint_card.show()
	_centre_hint.call_deferred()


func _centre_hint() -> void:
	hint_card.reset_size()
	hint_card.offset_left = -hint_card.size.x * 0.5
	hint_card.offset_right = hint_card.size.x * 0.5
	hint_card.offset_top = hint_card.offset_bottom - hint_card.size.y


func dismiss_hint(key := "") -> void:
	if not hint_card.visible or (not key.is_empty() and hint_card.get_meta("key", "") != key):
		return
	ui.mark_hint(str(hint_card.get_meta("key", "")))
	hint_card.hide()
