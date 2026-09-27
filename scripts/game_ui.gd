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
var try_input: TextEdit
var try_selected: Array[String] = []
var working_label: Label
var working_clock := 0.0
var talk_npc := ""
var talk_input: LineEdit
var talk_status: Label
var talk_waiting := false
var encounter_view: Dictionary = {} # The encounter as last seen (kept to show how it ended).
var encounter_over := false
const CAPABILITY_NOTES := {"expected": "", "untested": "  (untested)", "observed": "  (seen working)",
	"failed": "  (didn't work when tried)"}
const OUTCOME_TITLES := {
	"success": "You made something", "failed": "It didn't work", "blocked": "Something is missing",
	"needs_clarification": "One question", "unsupported": "Beyond this world's rules",
	"unresolved": "Nothing was decided", "partial_success": "Partly done",
}
const FLAG_WORDS := {
	"rigid": "rigid", "flexible": "flexible", "sharp_edge": "sharp", "tieable": "can be tied",
	"adhesive": "sticky", "container": "holds things", "watertight": "watertight", "floats": "floats",
	"combustible": "would burn", "ferromagnetic": "attracted to magnets", "magnetized": "magnetic",
	"magnet_source": "strongly magnetic", "light_source": "gives light", "heat_source": "gives heat",
	"sound_loud": "loud", "reflective": "reflective", "indicates_direction": "points one way",
	"measures_length": "measures length", "stable_support": "stands steady", "fulcrum": "works as a pivot",
}

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
	game.hint = label("WASD / arrows  Move     Shift  Run     E  Interact     F  Inspect     T  Try something     I  Bag     Esc  Pause", 14)
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
	debug_box.add_child(button("AI TRACES  [F4]", game.open_traces))
	game.trace_panel.hide()
	game.victory_panel = panel(self, Vector2(380, 230), Vector2(520, 190))
	var win_box := VBoxContainer.new()
	game.victory_panel.add_child(win_box)
	win_box.add_child(label("Beyond the gate", 30))
	win_box.add_child(label("You reached the end of this playable area.", 17))
	game.victory_route = label("", 16)
	game.victory_route.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	game.victory_route.custom_minimum_size.x = 480
	game.victory_route.add_theme_color_override("font_color", GOLD)
	win_box.add_child(game.victory_route)
	win_box.add_child(button("Return to title", game._back_to_menu))
	game.victory_panel.hide()
	chrome.hide()

func _process(delta: float) -> void:
	toast_time = maxf(0, toast_time - delta)
	toast.modulate.a = minf(1.0, toast_time)
	shade.visible = game.menu.visible or modal.visible or game.victory_panel.visible
	chrome.visible = not game.menu.visible
	prompt.visible = not prompt.text.is_empty() and not modal.visible and not game.victory_panel.visible
	if modal_kind == "working" and is_instance_valid(working_label):
		working_clock += delta
		working_label.text = "You set to work" + ".".repeat(1 + int(working_clock * 2.0) % 3)
	if modal_kind == "encounter" and talk_waiting and is_instance_valid(talk_status):
		working_clock += delta
		talk_status.text = "Everyone acts at once" + ".".repeat(1 + int(working_clock * 2.0) % 3)

func notify(text: String) -> void:
	toast.text = text
	toast_time = 4.5

func close_modal() -> void:
	if game.request_busy or modal_kind == "death":
		return
	if modal_kind == "encounter" and not encounter_over and not _encounter().is_empty():
		game.encounter_act("leave", "", "") # Closing the panel face to face with someone is walking away.
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
		row.add_child(object_icon(obj))
		var made := "  ·  made by you" if obj.get("created_by") == "player" else ""
		var description := label(str(obj.name).capitalize() + "\n" + str(obj.mass_kg) + " kg" + made, 17)
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
		var heading := HBoxContainer.new()
		heading.add_theme_constant_override("separation", 14)
		body.add_child(heading)
		heading.add_child(object_icon(obj, 96))
		var summary := label(str(obj.get("description", "")), 17)
		summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		summary.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		heading.add_child(summary)
		var facts := "Condition: " + str(obj.condition).capitalize() + "\nWeight: " + str(obj.mass_kg) + " kg"
		if obj.get("length_m") != null:
			facts += "\nLength: about %s m" % obj.length_m
		if not obj.get("materials", []).is_empty():
			facts += "\nMade of: " + ", ".join(obj.materials)
		var feel := flag_words(obj.get("flags", []))
		if not feel.is_empty():
			facts += "\nIt is: " + feel
		paragraph(body, facts)
		var owner_name := "You" if obj.owner_id == "player" else "Nobody"
		for npc in game.run_state.npcs:
			if npc.id == obj.owner_id:
				owner_name = str(npc.name)
		paragraph(body, "Belongs to: " + owner_name + (" (lent to you)" if obj.get("lent_to") == "player" else ""))
		if obj.get("created_by") == "player":
			paragraph(body, provenance(obj))
			capability_lines(body, obj)
			if game.is_placeholder(obj):
				paragraph(body, "(Its picture is still being painted.)" if game.sprite_status(obj) == "polling"
					else "(Its picture couldn't be painted; a stand-in is shown.)")
		paragraph(body, "Carried in your bag." if obj.holder_id == "player" else "Lying here in the world.")
		if float(obj.get("capacity_l", 0)) > 0:
			paragraph(body, "Water: %s / %s litres" % [obj.get("water_l", 0), obj.capacity_l])
		if obj.holder_id == "player":
			body.add_child(button("Back to belongings", open_bag))
		elif "carry" in obj.capabilities and (obj.owner_id == null or obj.owner_id == "player"):
			body.add_child(button("Pick up", game._quick_action.bind("take", id)))
		elif "carry" in obj.capabilities:
			paragraph(body, "It isn't yours to pick up freely. You could still try something with it (T).")
		return
	for npc in game.run_state.npcs:
		if npc.id == id:
			var alive: bool = npc.get("alive", true)
			var painted := game.get_node_or_null("NPCs/" + str(id) + "/PaintedActor")
			if painted and alive:
				painted.play_gesture("greet")
			var body := begin_modal(str(npc.name) + ("" if alive else " (dead)"), "person")
			paragraph(body, str(npc.role))
			var injuries: Array = npc.get("injuries", [])
			if not alive:
				paragraph(body, str(npc.name) + " lies still on the ground." + (
					"\nCause: " + str(injuries[-1]) if not injuries.is_empty() else ""))
			elif not injuries.is_empty():
				paragraph(body, str(npc.name) + " is hurt: " + "; ".join(injuries) + ".")
			var their_mind = npc.get("mind")
			if alive:
				var met: bool = typeof(their_mind) == TYPE_DICTIONARY and their_mind.get("met", false)
				paragraph(body, "You have spoken before." if met else "You have not spoken yet.")
				body.add_child(button("Talk  [E]", open_talk.bind(str(id))))
			if game.run_state.get("mode", "") == "developer" and typeof(their_mind) == TYPE_DICTIONARY:
				var lines := PackedStringArray()
				for memory in their_mind.get("memories", []):
					lines.append("• (%s) %s" % [memory.source, memory.summary])
				var job = their_mind.get("job")
				var view: Dictionary = their_mind.get("regard", {})
				paragraph(body, "DEVELOPER: fear %s · anger %s · trust %s · suspicion %s · doing: %s\n%s" % [
					their_mind.get("feelings", {}).get("fear", 0), their_mind.get("feelings", {}).get("anger", 0),
					view.get("trust", "-"), view.get("suspicion", "-"),
					str(job.kind) if typeof(job) == TYPE_DICTIONARY else "routine",
					"\n".join(lines) if not lines.is_empty() else "No memories of the stranger."])
			return

func npc_record(id: String) -> Dictionary:
	for npc in game.run_state.get("npcs", []):
		if npc.id == id:
			return npc
	return {}


## The encounter panel: face to face with one or more people, in rounds. Everything you and they
## do in a round happens at the same moment; the log shows it, round by round.
func open_talk(id: String, prefill := "") -> void:
	open_encounter(id, prefill)


func _encounter() -> Dictionary:
	var current = game.run_state.get("encounter")
	return current if typeof(current) == TYPE_DICTIONARY else {}


func open_encounter(target := "", prefill := "") -> void:
	if game.run_state.is_empty() or not game.gameplay_active:
		return
	var current := _encounter()
	if not current.is_empty():
		encounter_view = current
		encounter_over = false
	elif target != "" and not npc_record(target).get("alive", true):
		inspect(target)
		return
	elif target != "":
		encounter_view = {}
		encounter_over = false
	var people: Array = current.get("participants", []) if not current.is_empty() else \
		(encounter_view.get("participants", []) if encounter_over else [target])
	if target != "":
		talk_npc = target
	elif not talk_npc in people and not people.is_empty():
		talk_npc = str(current.get("opened_by", people[0])) if current.get("opened_by", "") in people else str(people[0])
	var first_open := modal_kind != "encounter"
	talk_waiting = false
	var names: PackedStringArray = []
	for id in people:
		names.append(str(npc_record(str(id)).get("name", "?")))
	var body := begin_modal(" & ".join(names) if not names.is_empty() else "Nobody", "encounter")
	if not encounter_over:
		for child in modal_box.get_child(0).get_children(): # "Walk away" is the way out, not "Close".
			if child is Button:
				child.hide()
	var cast := HFlowContainer.new()
	cast.add_theme_constant_override("h_separation", 8)
	body.add_child(cast)
	for id in people:
		var npc := npc_record(str(id))
		var health := float(npc.get("health", 100))
		var state_word := "dead" if not npc.get("alive", true) else "unhurt" if health >= 100 else \
			"wounded" if health > 30 else "badly wounded"
		var chip := button("%s · %s · %s" % [npc.get("name", "?"), str(npc.get("role", "")).to_lower(), state_word],
			_address.bind(str(id)))
		chip.toggle_mode = true
		chip.button_pressed = str(id) == talk_npc
		chip.add_theme_font_size_override("font_size", 14)
		chip.custom_minimum_size.y = 32
		cast.add_child(chip)
	if game.run_state.get("mode", "") == "developer" and typeof(game.last_trace) == TYPE_DICTIONARY \
			and game.last_trace.get("kind") == "talk":
		talk_trace(body, game.last_trace) # Above the log, so the latest lines stay in view.
	var log: Array = encounter_view.get("log", [])
	if log.is_empty():
		var their_mind = npc_record(talk_npc).get("mind") if typeof(npc_record(talk_npc).get("mind")) == TYPE_DICTIONARY else {}
		for turn in their_mind.get("talk", []): # Earlier conversations with this person.
			_log_line(body, ("You: " if turn.who == "stranger" else str(npc_record(talk_npc).name) + ": ") + "“" + str(turn.text) + "”",
				turn.who != "stranger", true)
		paragraph(body, "%s looks you over. Say something." % npc_record(talk_npc).get("name", ""))
	var shown_round := -1
	for entry in log:
		if int(entry.get("round", 0)) != shown_round:
			shown_round = int(entry.get("round", 0))
			var heading := label("ROUND %d" % shown_round, 11)
			heading.add_theme_color_override("font_color", Color(0.86, 0.77, 0.56, 0.6))
			body.add_child(heading)
		_log_line(body, str(entry.text), str(entry.get("who", "")) != "player", false)
	talk_status = label("", 15)
	talk_status.add_theme_color_override("font_color", GOLD)
	talk_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(talk_status)
	if encounter_over:
		paragraph(body, "It's over." if game.run_state["player"].get("alive", true) else "")
		body.add_child(button("Continue", close_modal))
		_scroll_to_end.call_deferred(body)
		return
	talk_input = LineEdit.new()
	talk_input.placeholder_text = "Say something to %s, or describe what you do…" % npc_record(talk_npc).get("name", "them")
	talk_input.max_length = 500
	talk_input.add_theme_font_size_override("font_size", 17)
	talk_input.custom_minimum_size.y = 40
	talk_input.text_submitted.connect(func(_text: String) -> void: _submit_talk())
	body.add_child(talk_input)
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	actions.add_child(button("Say it  [Enter]", _submit_talk))
	actions.add_child(button("Do it", _submit_do))
	actions.add_child(button("Wait", _submit_simple.bind("wait")))
	actions.add_child(button("Walk away  [Esc]", close_modal))
	body.add_child(actions)
	var hint := label("Do it: an action, like “hand him the plank” or “swing the spear at her”. Everyone acts at the same moment.", 13)
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_color_override("font_color", Color(0.85, 0.82, 0.72, 0.6))
	body.add_child(hint)
	if first_open and current.get("reason", "talk") == "talk":
		var painted := game.get_node_or_null("NPCs/" + talk_npc + "/PaintedActor")
		if painted:
			painted.play_gesture("greet")
	talk_input.text = prefill
	talk_input.caret_column = prefill.length()
	talk_input.grab_focus.call_deferred()
	_scroll_to_end.call_deferred(body)


func _log_line(body: VBoxContainer, text: String, theirs: bool, faded: bool) -> void:
	var line := label(text, 16)
	line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if theirs:
		line.add_theme_color_override("font_color", Color("f3d99a"))
	if faded:
		line.modulate.a = 0.6
	body.add_child(line)


## The encounter has finished (they left, you walked away, the gate opened): show the last round.
func encounter_ended() -> void:
	if modal_kind == "encounter" and not encounter_over:
		encounter_over = true
		open_encounter()


func _address(id: String) -> void:
	talk_npc = id
	open_encounter(id, talk_input.text if is_instance_valid(talk_input) else "")


func _scroll_to_end(body: VBoxContainer) -> void:
	await get_tree().process_frame
	var scroll := body.get_parent() as ScrollContainer
	if is_instance_valid(scroll) and modal_kind == "encounter":
		scroll.scroll_vertical = int(scroll.get_v_scroll_bar().max_value)


func _submit_talk() -> void:
	var text := talk_input.text.strip_edges()
	if text.is_empty() or talk_waiting or game.request_busy:
		return
	game.encounter_act("say", text, talk_npc)


func _submit_do() -> void:
	var text := talk_input.text.strip_edges()
	if text.is_empty():
		talk_status.text = "Describe what you do first."
		return
	if not talk_waiting and not game.request_busy:
		game.encounter_act("do", text, talk_npc)


func _submit_simple(kind: String) -> void:
	if not talk_waiting and not game.request_busy:
		game.encounter_act(kind, "", talk_npc)


func talk_wait(text: String) -> void:
	talk_waiting = true
	working_clock = 0.0
	if is_instance_valid(talk_input):
		talk_input.editable = false
		if not text.is_empty():
			var said := label(text, 16)
			said.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			talk_status.get_parent().add_child(said)
			talk_status.get_parent().move_child(said, talk_status.get_index())


func talk_error(message: String) -> void:
	talk_waiting = false
	if modal_kind != "encounter" or not is_instance_valid(talk_status):
		notify(message)
		return
	talk_status.text = message
	if is_instance_valid(talk_input):
		talk_input.editable = true
		talk_input.grab_focus()


## Developer view of the last exchange: what Jev chose, how regard moved, what the voice was given.
func talk_trace(body: VBoxContainer, trace: Dictionary) -> void:
	var call: Dictionary = trace.get("call", {})
	var spoken: Dictionary = trace.get("voice", {})
	var change: Dictionary = trace.get("regard_change", {})
	var heading := label("DEVELOPER: LAST EXCHANGE", 12)
	heading.add_theme_color_override("font_color", GOLD)
	body.add_child(heading)
	paragraph(body, "Reply: %s (Jev's top choice: %s)\nTrust %+.2f · suspicion %+.2f\nDecider: %s · %d ms · $%s%s\nVoice: %s · %s · %d ms%s" % [
		str(trace.get("action")), str(trace.get("jev_choice")), float(change.get("trust", 0)), float(change.get("suspicion", 0)),
		_shown(call.get("provider")), int(call.get("latency_ms", 0)), _shown(call.get("cost_usd")),
		("\nFell back from " + str(call.fallback_from)) if call.get("fallback_from") != null else "",
		_shown(spoken.get("status")), _shown(spoken.get("model")), int(spoken.get("latency_ms", 0)),
		("\nVoice error: " + str(spoken.error)) if spoken.get("error") != null else ""])
	reveal(body, "What the decider saw", str(trace.get("situation", "")) + "\n\nOPTIONS AND ANSWERS\n" +
		JSON.stringify({"questions": trace.get("questions", {}), "answers": call.get("answers", {})}, "  "))
	reveal(body, "What the voice was given", JSON.stringify(trace.get("voice_context", {}), "  "))


func open_journal() -> void:
	if game.run_state.is_empty() or game.request_busy:
		return
	var body := begin_modal("Your journal", "journal")
	paragraph(body, "GET INSIDE THE CITY\nYou arrived from the future with only your knowledge. Explore, notice what is available, and consider what you could do with it.")
	var told := PackedStringArray()
	for claim in game.run_state.get("learned", []):
		told.append("• %s: “%s”" % [claim.name, claim.said])
	if not told.is_empty():
		var people := label("PEOPLE: WHAT YOU'VE BEEN TOLD", 12)
		people.add_theme_color_override("font_color", GOLD)
		body.add_child(people)
		paragraph(body, "\n".join(told))
	var deals := PackedStringArray()
	for deal in game.run_state.get("agreements", {}).values():
		if deal.has("issuer"):
			var status: String = {"proposed": "offered", "accepted": "you agreed", "fulfilled": "done"}.get(str(deal.status), str(deal.status))
			deals.append("• %s asked you to %s (%s)" % [npc_record(str(deal.issuer)).get("name", "Someone"), deal.task, status])
	if not deals.is_empty():
		var heading := label("DEALS", 12)
		heading.add_theme_color_override("font_color", GOLD)
		body.add_child(heading)
		paragraph(body, "\n".join(deals))
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


func object_icon(obj: Dictionary, edge := 64) -> TextureRect:
	var icon := TextureRect.new()
	icon.texture = game.texture_for(obj)
	icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	icon.custom_minimum_size = Vector2(edge, edge)
	icon.set_meta("object_id", str(obj.id))
	if icon.texture == null:
		var waiting := preload("res://scripts/loading_icon.gd").new()
		waiting.name = "Painting"
		waiting.missing = game.sprite_status(obj) in ["failed", "none"]
		icon.add_child(waiting)
	return icon


## Swap "Painting…" for the picture in the open panel once it arrives.
func refresh_icons() -> void:
	for icon in modal_box.find_children("*", "TextureRect", true, false):
		if icon.has_meta("object_id") and game.run_state.get("objects", {}).has(icon.get_meta("object_id")):
			var obj: Dictionary = game.run_state.objects[icon.get_meta("object_id")]
			icon.texture = game.texture_for(obj)
			var waiting := icon.get_node_or_null("Painting")
			if waiting and icon.texture != null:
				icon.remove_child(waiting)
				waiting.queue_free()
			elif waiting:
				waiting.missing = game.sprite_status(obj) in ["failed", "none"]


func flag_words(flags: Array) -> String:
	var words: PackedStringArray = []
	for flag in flags:
		words.append(str(FLAG_WORDS.get(flag, flag)))
	return ", ".join(words)


func _listing(names: PackedStringArray) -> String:
	if names.size() <= 1:
		return "".join(names)
	return ", ".join(names.slice(0, names.size() - 1)) + " and " + names[names.size() - 1]


func provenance(obj: Dictionary) -> String:
	var objects: Dictionary = game.run_state.objects
	var parts: PackedStringArray = []
	for id in obj.get("components", []):
		parts.append("a " + str(objects[id].name) if objects.has(id) else str(id))
	var tools: PackedStringArray = []
	for id in obj.get("tools_used", []):
		tools.append("the " + str(objects[id].name) if objects.has(id) else str(id))
	var cut_from: bool = obj.get("components", []).size() == 1 and objects.has(obj.components[0]) \
		and objects[obj.components[0]].has("became")
	var text := ("Cut by you from " if cut_from else "Made by you from ") + _listing(parts)
	if not tools.is_empty():
		text += ", using " + _listing(tools)
	return text + ".\nYour words: “" + str(obj.get("created_text", "")) + "”"


func capability_lines(body: VBoxContainer, obj: Dictionary) -> void:
	var lines: PackedStringArray = []
	for capability in obj.get("known_capabilities", []):
		lines.append("• " + str(capability.text) + str(CAPABILITY_NOTES.get(str(capability.status), "")))
	if not lines.is_empty():
		paragraph(body, "What it might do:\n" + "\n".join(lines))


func open_try(prefill := "") -> void:
	if game.run_state.is_empty() or game.request_busy or not game.gameplay_active:
		return
	var body := begin_modal("Try something", "try")
	paragraph(body, "Describe what you want to do, in your own words. You can use what you carry and whatever or whoever is within reach.")
	if not game.ai_ready():
		var warning := label("AI judging isn't set up on this computer yet (no OpenAI key on the backend). You can still try; the game will tell you honestly that it couldn't decide.", 14)
		warning.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		warning.add_theme_color_override("font_color", GOLD)
		body.add_child(warning)
	try_input = TextEdit.new()
	try_input.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	try_input.custom_minimum_size = Vector2(0, 96)
	try_input.placeholder_text = "What do you want to do?"
	try_input.add_theme_font_size_override("font_size", 17)
	try_input.text = prefill
	try_input.gui_input.connect(_on_try_key)
	body.add_child(try_input)
	try_selected.clear()
	var items: Array[Dictionary] = game.try_candidates()
	if items.is_empty():
		paragraph(body, "You carry nothing, and nothing is within reach. Walk closer to things or people first.")
	else:
		body.add_child(label("Within reach (optional: click to point at something)", 14))
		var chips := HFlowContainer.new()
		chips.add_theme_constant_override("h_separation", 6)
		chips.add_theme_constant_override("v_separation", 6)
		for obj in items:
			var chip := button(str(obj.name) + _chip_note(obj), func() -> void: pass)
			chip.custom_minimum_size.y = 34
			chip.toggle_mode = true
			if not obj.get("person", false):
				chip.icon = game.texture_for(obj)
			chip.expand_icon = false
			chip.add_theme_constant_override("icon_max_width", 26)
			chip.add_theme_font_size_override("font_size", 14)
			chip.toggled.connect(_on_chip.bind(str(obj.id), str(obj.name)))
			chips.add_child(chip)
		body.add_child(chips)
	body.add_child(button("Do it  [Enter]", _submit_try))
	try_input.grab_focus.call_deferred()
	try_input.set_caret_column.call_deferred(prefill.length())


func _chip_note(obj: Dictionary) -> String:
	if obj.get("person", false):
		return "" if obj.alive else "  (dead)"
	if obj.holder_id == "player":
		return "  (carried)"
	var owner: String = game.owner_name(obj)
	if obj.get("lent_to") == "player":
		return "  (%s's, lent to you)" % owner
	return "  (%s's)" % owner if not owner.is_empty() and owner != "you" else ""


func _on_chip(pressed: bool, id: String, item_name: String) -> void:
	if pressed and id not in try_selected:
		try_selected.append(id)
		if item_name not in try_input.text:
			try_input.insert_text_at_caret(("" if try_input.text.ends_with(" ") or try_input.text.is_empty() else " ") + "the " + item_name + " ")
	elif not pressed:
		try_selected.erase(id)
	try_input.grab_focus()


func _on_try_key(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.shift_pressed and \
			(event.keycode == KEY_ENTER or event.keycode == KEY_KP_ENTER):
		try_input.accept_event()
		_submit_try()


func _submit_try() -> void:
	var text := try_input.text.strip_edges()
	if text.is_empty():
		notify("Describe what you want to try first.")
		return
	game._try_something(text, try_selected.duplicate())


func show_working(text: String) -> void:
	var body := begin_modal("Working", "working")
	paragraph(body, "“" + text + "”")
	working_clock = 0.0
	working_label = label("You set to work.", 22)
	working_label.add_theme_color_override("font_color", GOLD)
	body.add_child(working_label)
	paragraph(body, "The world is working out whether this can be done. Time stands still while you wait.")


## The object a make step produced; older journal entries only record "made".
func _crafted(entry: Dictionary):
	if entry.has("crafted"):
		return entry.crafted
	return entry.get("made") if str(entry.get("action", "make")) == "make" else null


func _result_title(entry: Dictionary) -> String:
	var category := str(entry.category)
	if category != "success":
		return str(OUTCOME_TITLES.get(category, "Result"))
	# Several steps can succeed at once; title the most striking outcome.
	var harm = entry.get("harm")
	if typeof(harm) == TYPE_DICTIONARY:
		return {"killed": "Killed", "wounded": "Wounded", "missed": "You missed"}.get(str(harm.result), "Done")
	if _crafted(entry) != null:
		return str(OUTCOME_TITLES.success)
	if typeof(entry.get("transformed")) == TYPE_DICTIONARY:
		return "It's done"
	var shown = entry.get("demonstration")
	if typeof(shown) == TYPE_DICTIONARY:
		return "You showed it" if shown.works else "It didn't work"
	if typeof(entry.get("give")) == TYPE_DICTIONARY:
		return "Given"
	if typeof(entry.get("fill")) == TYPE_DICTIONARY:
		return "Filled"
	if not entry.get("taken_ids", []).is_empty():
		return "Taken"
	return "Done"


## "a deep cut to the arm" -> "A deep cut to the arm." (String.capitalize() would title-case every word.)
func _sentence(text: String) -> String:
	text = text.strip_edges()
	if text.is_empty():
		return text
	text = text.left(1).to_upper() + text.substr(1)
	return text if text.right(1) in [".", "!", "?"] else text + "."


func _object_rows(body: VBoxContainer, ids: Array) -> void:
	var seen := {}
	for id in ids:
		var obj: Dictionary = game.run_state.objects.get(id, {})
		if obj.is_empty():
			continue
		var key := str(obj.name)
		seen[key] = seen.get(key, []) + [obj]
	for key in seen:
		var group: Array = seen[key]
		var obj: Dictionary = group[0]
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		body.add_child(row)
		row.add_child(object_icon(obj, 56))
		var where := "in your bag" if obj.holder_id == "player" else \
			("too heavy to carry" if not "carry" in obj.capabilities else "on the ground")
		var count := "%d × " % group.size() if group.size() > 1 else ""
		var weight := str(obj.mass_kg) + " kg" + (" each" if group.size() > 1 else "")
		var line := label(count + str(obj.name).capitalize() + "  ·  " + weight + "  ·  " + where, 16)
		line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(line)


func show_craft_result(entry: Dictionary, trace) -> void:
	var category := str(entry.category)
	var body := begin_modal(_result_title(entry), "result")
	var said := label("“" + str(entry.text) + "”", 15)
	said.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	said.add_theme_color_override("font_color", Color(0.85, 0.82, 0.72, 0.75))
	body.add_child(said)
	paragraph(body, str(entry.reason))
	for claim in entry.get("property", []):
		var owner := str(claim.owner_id)
		for npc in game.run_state.npcs:
			if npc.id == claim.owner_id:
				owner = str(npc.name)
		var note := label("The %s belongs to %s (%s)." % [claim.name, owner, str(claim.how).replace("_", " ")], 15)
		note.add_theme_color_override("font_color", GOLD)
		body.add_child(note)
	# Everything a committed step changed is shown, even when a later step failed.
	_object_rows(body, entry.get("taken_ids", []))
	var transformed = entry.get("transformed")
	if typeof(transformed) == TYPE_DICTIONARY:
		_object_rows(body, transformed.get("into", []))
	var harm = entry.get("harm")
	if typeof(harm) == TYPE_DICTIONARY:
		var victim := str(harm.target_id)
		for npc in game.run_state.npcs:
			if npc.id == harm.target_id:
				victim = str(npc.name)
		paragraph(body, {"killed": "%s is dead.", "wounded": "%s is wounded.", "missed": "%s is unhurt."}.get(
			str(harm.result), "%s") % victim + ("" if str(harm.result) == "missed" else " " + _sentence(str(harm.injury))))
		if not harm.get("witnesses", []).is_empty():
			paragraph(body, "Others nearby saw it.")
	var shown = entry.get("demonstration")
	if typeof(shown) == TYPE_DICTIONARY:
		var seen := label("What people saw: " + str(shown.observed), 16)
		seen.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		seen.add_theme_color_override("font_color", GOLD)
		body.add_child(seen)
		if game.run_state.objects.has(shown.object_id):
			capability_lines(body, game.run_state.objects[shown.object_id])
	var given = entry.get("give")
	if typeof(given) == TYPE_DICTIONARY:
		paragraph(body, "%s now has the %s." % [given.recipient_name, " and the ".join(given.names)])
	var filled = entry.get("fill")
	if typeof(filled) == TYPE_DICTIONARY and game.run_state.objects.has(filled.container_id):
		var container: Dictionary = game.run_state.objects[filled.container_id]
		paragraph(body, "The %s holds %s of %s litres." % [container.name, container.water_l, container.capacity_l])
	var made = _crafted(entry)
	if made != null and game.run_state.objects.has(made):
		var obj: Dictionary = game.run_state.objects[made]
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 14)
		body.add_child(row)
		row.add_child(object_icon(obj, 104))
		var about := VBoxContainer.new()
		about.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(about)
		var title := label(str(obj.name).capitalize(), 22)
		title.add_theme_color_override("font_color", GOLD)
		about.add_child(title)
		paragraph(about, str(obj.get("description", "")))
		var facts := "Made of: " + ", ".join(obj.get("materials", [])) + "\nWeight: " + str(obj.mass_kg) + " kg"
		var feel := flag_words(obj.get("flags", []))
		if not feel.is_empty():
			facts += "\nIt is: " + feel
		paragraph(body, facts)
		capability_lines(body, obj)
		paragraph(body, "It's in your bag." if obj.holder_id == "player"
			else "It's too heavy to carry with everything else, so it's at your feet.")
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	if category == "needs_clarification":
		actions.add_child(button("Answer", open_try.bind(str(entry.text) + "\n")))
	actions.add_child(button("Try something else", open_try))
	actions.add_child(button("Close", close_modal))
	body.add_child(actions)
	if game.run_state.get("mode", "") == "developer" and typeof(trace) == TYPE_DICTIONARY:
		trace_view(body, trace)


func show_death(reason: String) -> void:
	var body := begin_modal("You died", "death")
	for child in modal_box.get_child(0).get_children(): # No "Close" on the death screen.
		if child is Button:
			child.hide()
	paragraph(body, reason)
	paragraph(body, "The people here remembered what you did, and acted on it.")
	body.add_child(button("Try again from before the trouble began", game.rewind))
	body.add_child(button("Start a new journey", func() -> void:
		modal_kind = ""
		game._back_to_menu()))


func show_craft_error(problem: String, text: String) -> void:
	var body := begin_modal("Nothing happened", "result")
	paragraph(body, problem)
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 8)
	actions.add_child(button("Try again", open_try.bind(text)))
	actions.add_child(button("Close", close_modal))
	body.add_child(actions)


## Developer-only view of one judge call: what was sent, what came back, what code changed.
func trace_view(body: VBoxContainer, trace: Dictionary) -> void:
	var heading := label("DEVELOPER TRACE", 12)
	heading.add_theme_color_override("font_color", GOLD)
	body.add_child(heading)
	var judged: Dictionary = trace.get("judge", {})
	var validator: Dictionary = trace.get("validator", {})
	var summary := "Judge: %s  ·  model %s  ·  prompt %s  ·  reasoning %s\n%d ms  ·  %d in / %d out tokens  ·  %d attempt(s)" % [
		_shown(judged.get("status")), _shown(judged.get("model")), _shown(judged.get("prompt_version")),
		_shown(judged.get("reasoning")), int(judged.get("latency_ms", 0)), int(judged.get("input_tokens", 0)),
		int(judged.get("output_tokens", 0)), int(judged.get("attempts", 0))]
	if judged.get("error") != null:
		summary += "\nError: " + str(judged.error)
	for failure in judged.get("attempt_errors", []):
		summary += "\nAttempt error: " + str(failure)
	var proposed = judged.get("result")
	if typeof(proposed) == TYPE_DICTIONARY:
		summary += "\nModel proposed: %s  →  validator committed: %s" % [proposed.get("outcome"), validator.get("category")]
	else:
		summary += "\nValidator committed: " + str(validator.get("category"))
	var notes: Array = validator.get("notes", [])
	summary += "\nValidator notes: " + ("none (proposal accepted as is)" if notes.is_empty() else "")
	for note in notes:
		summary += "\n  • " + str(note)
	paragraph(body, summary)
	var raw = judged.get("raw_output")
	var parsed = JSON.parse_string(str(raw)) if raw != null else null
	reveal(body, "Model output (raw)", JSON.stringify(parsed, "  ") if parsed != null else str(raw))
	reveal(body, "Context sent to the model", JSON.stringify(trace.get("context", {}), "  "))
	if typeof(validator.get("new_spec")) == TYPE_DICTIONARY:
		reveal(body, "Object committed by code", JSON.stringify(validator.new_spec, "  "))


func _shown(value) -> String:
	return "-" if value == null else str(value)


func reveal(body: VBoxContainer, title: String, text: String) -> void:
	var box := TextEdit.new()
	box.text = text
	box.editable = false
	box.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	box.custom_minimum_size = Vector2(0, 220)
	box.add_theme_font_size_override("font_size", 13)
	box.visible = false
	var toggle := button("Show " + title.to_lower(), func() -> void: pass)
	toggle.custom_minimum_size.y = 32
	toggle.add_theme_font_size_override("font_size", 13)
	toggle.pressed.connect(func() -> void:
		box.visible = not box.visible
		toggle.text = ("Hide " if box.visible else "Show ") + title.to_lower())
	body.add_child(toggle)
	body.add_child(box)


func show_traces(data: Dictionary) -> void:
	var body := begin_modal("AI traces", "traces")
	var ai: Dictionary = data.get("ai", {})
	paragraph(body, "AI mode: %s  ·  judge %s (%s)  ·  images %s (%s)\nPeople decide with: %s%s" % [
		ai.get("mode"), "on" if ai.get("judge") else "off", ai.get("judge_model"),
		"on" if ai.get("images") else "off", ai.get("image_model"), _shown(ai.get("decider")),
		(" (" + str(ai.get("jev_model")) + " via " + str(ai.get("jev_provider")) + ")") if ai.get("decider") == "jev" else ""])
	var traces: Array = data.get("traces", [])
	if traces.is_empty():
		paragraph(body, "No attempts yet. Press T in the world to try making something.")
	for trace in traces:
		var title := label("“" + str(trace.get("text", "")) + "”", 17)
		title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		title.add_theme_color_override("font_color", GOLD)
		body.add_child(title)
		trace_view(body, trace)
		body.add_child(HSeparator.new())
	var thoughts: Array = data.get("minds", [])
	if not thoughts.is_empty():
		body.add_child(label("PEOPLE'S DECISIONS (newest first)", 12))
		for thought in thoughts:
			var call: Dictionary = thought.get("call", {})
			var what := str(thought.get("action", thought.get("result", thought.get("skipped", "-"))))
			paragraph(body, "%s (%s) → %s\n%s · %s · %d ms · $%s%s%s" % [
				str(thought.npc_id).trim_prefix("npc_"), thought.get("why", ""), what, _shown(call.get("provider")),
				_shown(call.get("model")), int(call.get("latency_ms", 0)), _shown(call.get("cost_usd")),
				(" · one request for %d people" % int(thought.get("people_in_request", 1))) if thought.get("shared_request", false) else "",
				("\nFell back from " + str(call.fallback_from)) if call.get("fallback_from") != null else ""])
			reveal(body, "What %s's decider saw" % str(thought.npc_id).trim_prefix("npc_"),
				str(thought.get("situation", "")) + "\n\nOPTIONS AND ANSWERS\n" +
				JSON.stringify({"questions": thought.get("questions", {}), "answers": call.get("answers", {})}, "  "))
			if thought.get("kind") == "talk":
				var spoken: Dictionary = thought.get("voice", {})
				paragraph(body, "You: “%s”\nSaid: “%s”\nVoice: %s · %s · %d ms" % [thought.get("text", ""),
					thought.get("reply", ""), _shown(spoken.get("status")), _shown(spoken.get("model")),
					int(spoken.get("latency_ms", 0))])
				reveal(body, "What the voice was given", JSON.stringify(thought.get("voice_context", {}), "  "))
		body.add_child(HSeparator.new())
	var sprites: Array = data.get("assets", [])
	if not sprites.is_empty():
		body.add_child(label("SPRITES", 12))
		for sprite in sprites:
			var info: Dictionary = sprite.get("call", {})
			paragraph(body, "%s  ·  %s  ·  %s  ·  %d ms%s" % [sprite.get("record", {}).get("name"), sprite.status,
				_shown(info.get("model")), int(info.get("latency_ms", 0)),
				("\nError: " + str(info.error)) if info.get("error") != null else ""])
			if sprite.status in ["failed", "disabled"]:
				body.add_child(button("Retry painting " + str(sprite.object_id), game.retry_sprite.bind(str(sprite.asset_id))))
			if info.has("prompt"):
				reveal(body, "Image prompt for " + str(sprite.object_id), str(info.prompt))
	var calls: Array = data.get("model_calls", [])
	if not calls.is_empty():
		var lines: PackedStringArray = []
		for entry in calls:
			lines.append("%s  %s  %d ms  %d/%d tok  %s" % [entry.role, _shown(entry.model), int(entry.latency_ms),
				int(entry.input_tokens), int(entry.output_tokens), "ok" if entry.ok else "FAILED"])
		reveal(body, "Model call log", "\n".join(lines))
	reveal(body, "Judge system prompt (" + str(data.get("judge_prompt_version", "")) + ")", str(data.get("judge_system_prompt", "")))
	reveal(body, "Voice system prompt", str(data.get("voice_system_prompt", "")))
