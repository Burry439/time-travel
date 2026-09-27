extends Control
const INK := Color("182522")
const GOLD := Color("dbc58f")
var game: Node2D
var chrome: Control
var modal: PanelContainer
var modal_box: VBoxContainer
var modal_kind := ""
var prompt: Label
var toast: Label
var toast_time := 0.0
var bag_button: Button
var area: Label
var shade: ColorRect

func label(text: String, font_size := 18) -> Label:
	var node := Label.new()
	node.text = text
	node.add_theme_font_size_override("font_size", font_size)
	node.add_theme_color_override("font_color", Color("f1ead7"))
	return node

func style(color: Color) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = color
	box.border_color = Color(0.70, 0.63, 0.43, 0.5)
	box.set_border_width_all(1)
	box.set_corner_radius_all(7)
	box.set_content_margin_all(18)
	return box

func button(text: String, call: Callable) -> Button:
	var node := Button.new()
	node.text = text
	node.custom_minimum_size.y = 40
	node.add_theme_stylebox_override("normal", style(Color("293a32")))
	node.add_theme_stylebox_override("hover", style(Color("41533d")))
	node.add_theme_stylebox_override("pressed", style(Color("536044")))
	node.add_theme_stylebox_override("focus", style(Color(0.48, 0.46, 0.30, 0.35)))
	node.add_theme_font_size_override("font_size", 16)
	node.pressed.connect(call)
	return node

func panel(parent: Node, at: Vector2, dimensions: Vector2) -> PanelContainer:
	var node := PanelContainer.new()
	node.position = at
	node.custom_minimum_size = dimensions
	node.add_theme_stylebox_override("panel", style(Color(0.07, 0.12, 0.10, 0.94)))
	parent.add_child(node)
	return node

func build(owner_game: Node2D) -> void:
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	chrome = Control.new()
	chrome.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	chrome.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(chrome)
	var objective := panel(chrome, Vector2(24, 24), Vector2(304, 89))
	objective.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var objective_box := VBoxContainer.new()
	objective.add_child(objective_box)
	area = label("THE SOUTH ROAD", 12)
	area.add_theme_color_override("font_color", GOLD)
	objective_box.add_child(area)
	objective_box.add_child(label("Find a way into the city", 21))
	game.hud = label("The gate lies to the north ↑", 13)
	objective_box.add_child(game.hud)
	var buttons := HBoxContainer.new()
	buttons.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	buttons.position = Vector2(-378, 24)
	buttons.add_theme_constant_override("separation", 8)
	chrome.add_child(buttons)
	bag_button = button("Bag  [I]", open_bag)
	buttons.add_child(bag_button)
	buttons.add_child(button("Journal  [J]", open_journal))
	buttons.add_child(button("Pause", open_pause))
	game.hint = label("WASD / arrows  Move     Shift  Run     E  Interact     F  Inspect     I  Bag     Esc  Pause", 14)
	game.hint.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT)
	game.hint.position = Vector2(24, -36)
	game.hint.add_theme_color_override("font_shadow_color", Color.BLACK)
	game.hint.add_theme_constant_override("shadow_offset_y", 2)
	chrome.add_child(game.hint)
	prompt = label("", 16)
	prompt.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	prompt.add_theme_stylebox_override("normal", style(Color(0.06, 0.10, 0.08, 0.92)))
	prompt.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	prompt.position = Vector2(-260, -113)
	prompt.size.x = 520
	chrome.add_child(prompt)
	toast = label("", 17)
	toast.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	toast.position = Vector2(-270, 132)
	toast.size.x = 540
	toast.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	toast.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	toast.add_theme_color_override("font_shadow_color", Color.BLACK)
	toast.add_theme_constant_override("shadow_offset_y", 2)
	chrome.add_child(toast)
	shade = ColorRect.new()
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.color = Color(0.025, 0.045, 0.035, 0.60)
	add_child(shade)
	game.menu = panel(self, Vector2.ZERO, Vector2(540, 420))
	game.menu.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	game.menu.offset_left = -270
	game.menu.offset_top = -210
	game.menu.offset_right = 270
	game.menu.offset_bottom = 210
	var menu_box := VBoxContainer.new()
	menu_box.add_theme_constant_override("separation", 13)
	game.menu.add_child(menu_box)
	menu_box.add_child(label("A STRANGER OUT OF TIME", 12))
	menu_box.add_child(label("The City Beyond", 38))
	var intro := label("A closed city. An unfamiliar world.\nThe only thing you brought is what you know.", 17)
	menu_box.add_child(intro)
	menu_box.add_child(button("Begin a journey", game._start.bind("normal")))
	menu_box.add_child(button("Continue last journey", game._resume))
	menu_box.add_child(button("Developer playtest", game._start.bind("developer")))
	game.message = label("Connecting…", 14)
	game.message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.message.custom_minimum_size.x = 490
	menu_box.add_child(game.message)
	modal = panel(self, Vector2.ZERO, Vector2(640, 510))
	modal.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	modal.offset_left = -320
	modal.offset_top = -255
	modal.offset_right = 320
	modal.offset_bottom = 255
	modal_box = VBoxContainer.new()
	modal_box.add_theme_constant_override("separation", 12)
	modal.add_child(modal_box)
	modal.hide()
	game.trace_panel = panel(self, Vector2(24, 142), Vector2(290, 210))
	var debug_box := VBoxContainer.new()
	game.trace_panel.add_child(debug_box)
	game.trace_text = label("", 13)
	debug_box.add_child(game.trace_text)
	game.gate_button = button("OPEN GATE (TEST)", game._toggle_gate)
	debug_box.add_child(game.gate_button)
	game.trace_panel.hide()
	game.victory_panel = panel(self, Vector2(380, 230), Vector2(520, 190))
	var win_box := VBoxContainer.new()
	game.victory_panel.add_child(win_box)
	win_box.add_child(label("Beyond the gate", 30))
	win_box.add_child(label("You reached the end of this playable area.", 17))
	win_box.add_child(button("Return to title", game._back_to_menu))
	game.victory_panel.hide()
	chrome.hide()

func _process(delta: float) -> void:
	toast_time = maxf(0, toast_time - delta)
	toast.modulate.a = minf(1.0, toast_time)
	shade.visible = game.menu.visible or modal.visible or game.victory_panel.visible
	chrome.visible = not game.menu.visible
	prompt.visible = not prompt.text.is_empty() and not modal.visible and not game.victory_panel.visible

func notify(text: String) -> void:
	toast.text = text
	toast_time = 4.5

func close_modal() -> void:
	if game.request_busy:
		return
	modal.hide()
	modal_kind = ""

func begin_modal(title: String, kind: String) -> VBoxContainer:
	for child in modal_box.get_children():
		modal_box.remove_child(child)
		child.queue_free()
	modal_kind = kind
	modal.show()
	var heading := HBoxContainer.new()
	modal_box.add_child(heading)
	var title_label := label(title, 28)
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title_label)
	heading.add_child(button("Close  [Esc]", close_modal))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.custom_minimum_size = Vector2(600, 380)
	modal_box.add_child(scroll)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 12)
	scroll.add_child(body)
	return body

func paragraph(body: VBoxContainer, text: String) -> void:
	var node := label(text, 17)
	node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	node.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(node)

func open_bag() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("Your belongings", "bag")
	var count := 0
	for id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state.objects[id]
		if obj.holder_id != "player":
			continue
		count += 1
		var row := HBoxContainer.new()
		body.add_child(row)
		var icon := TextureRect.new()
		var sprite := game.get_node_or_null("M2Objects/" + str(id)) as Sprite2D
		if sprite:
			icon.texture = sprite.texture
		icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		icon.custom_minimum_size = Vector2(64, 64)
		row.add_child(icon)
		var description := label(str(obj.name).capitalize() + "\n" + str(obj.mass_kg) + " kg", 17)
		description.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(description)
		row.add_child(button("Inspect", inspect.bind(str(id))))
		row.add_child(button("Put down", game._quick_action.bind("drop", str(id))))
	if count == 0:
		paragraph(body, "Your bag is empty.\n\nWalk up to a loose object and press E to pick it up. What might you make with the things you find?")
	else:
		paragraph(body, "Put down an item to leave it at your feet. Your belongings are saved with your journey.")

func inspect(id: String) -> void:
	var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
	if not obj.is_empty():
		var body := begin_modal(str(obj.name).capitalize(), "inspect")
		paragraph(body, "Condition: " + str(obj.condition).capitalize() + "\nWeight: " + str(obj.mass_kg) + " kg")
		var owner_name := "Nobody"
		for npc in game.run_state.npcs:
			if npc.id == obj.owner_id:
				owner_name = str(npc.name)
		paragraph(body, "Belongs to: " + owner_name)
		paragraph(body, "Carried in your bag." if obj.holder_id == "player" else "Lying here in the world.")
		if float(obj.get("capacity_l", 0)) > 0:
			paragraph(body, "Water: %s / %s litres" % [obj.get("water_l", 0), obj.capacity_l])
		if obj.holder_id == "player":
			body.add_child(button("Back to belongings", open_bag))
		elif obj.owner_id == null:
			body.add_child(button("Pick up", game._quick_action.bind("take", id)))
		return
	for npc in game.run_state.npcs:
		if npc.id == id:
			var painted := game.get_node_or_null("NPCs/" + str(id) + "/PaintedActor")
			if painted:
				painted.play_gesture("greet")
			var body := begin_modal(str(npc.name), "person")
			paragraph(body, str(npc.role))
			paragraph(body, "You have not spoken yet.\n\nConversations and free-form intentions are still being built. For now, explore the village and get a feel for the world.")
			return

func open_journal() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("Your journal", "journal")
	paragraph(body, "GET INSIDE THE CITY\nYou arrived from the future with only your knowledge. Explore, notice what is available, and consider what you could do with it.")
	var history: Array = game.run_state.get("journal", [])
	if history.is_empty():
		paragraph(body, "No discoveries recorded yet.")
	for index in range(history.size() - 1, maxi(-1, history.size() - 21), -1):
		paragraph(body, "• " + str(history[index].reason))

func open_pause() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("A moment to breathe", "pause")
	body.add_child(button("Continue exploring", close_modal))
	paragraph(body, "Camera distance")
	var zoom_slider := HSlider.new()
	zoom_slider.min_value = 0.75
	zoom_slider.max_value = 1.25
	zoom_slider.step = 0.05
	zoom_slider.value = game.camera_zoom
	zoom_slider.value_changed.connect(func(value: float) -> void: game.camera_zoom = value; game._save_settings())
	body.add_child(zoom_slider)
	paragraph(body, "Sound volume")
	var volume := HSlider.new()
	volume.min_value = 0
	volume.max_value = 1
	volume.step = 0.05
	volume.value = game.sound_volume
	volume.value_changed.connect(func(value: float) -> void: game.sound_volume = value; game._save_settings())
	body.add_child(volume)
	paragraph(body, "WASD / arrows to move • Shift to run\nE to interact • F to inspect • Tab to cycle nearby targets\nI for belongings • J for journal • Mouse wheel to zoom\n\nEvery completed action and movement is saved automatically.")
	body.add_child(button("Save and return to title", game._back_to_menu))
