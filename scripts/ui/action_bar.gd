extends PanelContainer
## The dialogue bar (GDD D-34, D-35, D-55): one panel along the bottom and one text line for everything.
## A Say / Do switch beside the line (Tab flips it) says which it is: words spoken aloud, or something you do
## (words in "quotes" inside a Do line are said as you do it). No guessing: the backend takes it as given.
## Face to face, rounds play back here line by line; alone, your attempts and their results appear in the
## same log. Esc (or ×) walks away or closes it.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const PaintedActor := preload("res://scripts/painted_actor.gd")
const HEIGHT := 272.0
const SAY_COLOUR := Color("2c5a63") # Speech: a cool slate blue.
const DO_COLOUR := Color("8a4b12") # Deeds: warm amber-brown.
const WORK_STAGES := ["You look over what you have", "You set to work", "You work at it",
	"You test what you've done", "Still at it"]

var ui: Control
var game: Node2D
var target := "" # Who you're addressing (a person's id) or the thing you're pointing at (an object id).
var selected: Array[String] = [] # Things pointed at, sent with the line.
var own_log: Array[Dictionary] = [] # Outside a face-to-face: results and notes, this session.
var encounter_view: Dictionary = {} # The encounter as last seen (kept to show how it ended).
var encounter_over := false
var round_playing := false
var waiting := false
var last_text := ""
var last_intent: Dictionary = {}
var wait_clock := 0.0
var hint_clock := 0.0
var mode := "say" # "say" or "do" (D-55).
var mode_chosen := false # The player picked it themselves this time the bar was open.

var portrait: TextureRect
var who: Label
var what: Label
var tabs: HBoxContainer
var intent_tag: Label
var close_button: Button
var scroll: ScrollContainer
var log_box: VBoxContainer
var chip_box: HFlowContainer
var line: LineEdit
var hint: Label
var pending: Control
var say_button: Button
var do_button: Button


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	offset_left = 10
	offset_right = -10
	offset_top = -HEIGHT - 8
	offset_bottom = -8
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 14)
	add_child(row)

	var left := VBoxContainer.new()
	left.custom_minimum_size.x = 128
	left.add_theme_constant_override("separation", 2)
	row.add_child(left)
	var frame := PanelContainer.new()
	frame.theme_type_variation = "SlotPanel"
	frame.custom_minimum_size = Vector2(122, 122)
	frame.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	left.add_child(frame)
	portrait = TextureRect.new()
	portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	frame.add_child(portrait)
	who = Label.new()
	who.add_theme_font_override("font", UITheme.serif(true))
	who.add_theme_font_size_override("font_size", 17)
	who.add_theme_color_override("font_color", UITheme.ACCENT)
	who.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	who.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	left.add_child(who)
	what = Label.new()
	what.theme_type_variation = "Small"
	what.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	what.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	left.add_child(what)

	var middle := VBoxContainer.new()
	middle.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	middle.add_theme_constant_override("separation", 4)
	row.add_child(middle)
	var top := HBoxContainer.new()
	top.add_theme_constant_override("separation", 6)
	middle.add_child(top)
	tabs = HBoxContainer.new()
	tabs.add_theme_constant_override("separation", 4)
	tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(tabs)
	intent_tag = Label.new()
	intent_tag.theme_type_variation = "Small"
	top.add_child(intent_tag)
	close_button = ui.button("✕  Walk away", escape, "Quiet")
	close_button.tooltip_text = "Esc"
	top.add_child(close_button)
	var paper := PanelContainer.new()
	paper.theme_type_variation = "InsetPanel"
	paper.size_flags_vertical = Control.SIZE_EXPAND_FILL
	middle.add_child(paper)
	scroll = ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	paper.add_child(scroll)
	log_box = VBoxContainer.new()
	log_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	log_box.add_theme_constant_override("separation", 5)
	scroll.add_child(log_box)
	var entry := HBoxContainer.new()
	entry.add_theme_constant_override("separation", 6)
	middle.add_child(entry)
	say_button = _mode_button("SAY", "say", "Words spoken aloud (Tab switches)")
	entry.add_child(say_button)
	do_button = _mode_button("DO", "do", "Something you do (Tab switches). Put words in “quotes” to say them as you do it.")
	entry.add_child(do_button)
	line = LineEdit.new()
	line.max_length = 500
	line.placeholder_text = "What do you say?"
	line.custom_minimum_size.y = 40
	line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	line.add_theme_font_size_override("font_size", 18)
	if "keep_editing_on_text_submit" in line:
		line.set("keep_editing_on_text_submit", true)
	line.text_submitted.connect(func(_text: String) -> void: submit())
	line.text_changed.connect(func(_text: String) -> void: _show_preview())
	line.gui_input.connect(_on_line_key)
	entry.add_child(line)
	hint = Label.new()
	hint.theme_type_variation = "Small"
	hint.clip_text = true
	middle.add_child(hint)

	var right := VBoxContainer.new()
	right.custom_minimum_size.x = 250
	right.add_theme_constant_override("separation", 4)
	row.add_child(right)
	var caption := Label.new()
	caption.theme_type_variation = "Caption"
	caption.text = "CLICK TO MENTION"
	right.add_child(caption)
	var chip_scroll := ScrollContainer.new()
	chip_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	chip_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	right.add_child(chip_scroll)
	chip_box = HFlowContainer.new()
	chip_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	chip_box.add_theme_constant_override("h_separation", 4)
	chip_box.add_theme_constant_override("v_separation", 4)
	chip_scroll.add_child(chip_box)
	set_mode("say")
	hide()


func _mode_button(text: String, value: String, tip: String) -> Button:
	var button := Button.new()
	button.text = text
	button.tooltip_text = tip
	button.focus_mode = Control.FOCUS_NONE
	button.custom_minimum_size = Vector2(64, 40)
	button.add_theme_font_override("font", UITheme.serif(true))
	button.add_theme_font_size_override("font_size", 16)
	button.pressed.connect(func() -> void:
		set_mode(value, true)
		_focus_line())
	return button


## Say or Do (D-55): the switch, the line's colour, the placeholder and the preview all follow it.
func set_mode(value: String, chosen := false) -> void:
	mode = "do" if value == "do" else "say"
	mode_chosen = mode_chosen or chosen
	for pair in [[say_button, "say", SAY_COLOUR], [do_button, "do", DO_COLOUR]]:
		var button: Button = pair[0]
		var on: bool = mode == pair[1]
		var colour: Color = pair[2]
		var fill := UITheme.flat(colour if on else Color(colour, 0.08), colour, 2, 6)
		for state_name in ["normal", "hover", "pressed", "focus"]:
			button.add_theme_stylebox_override(state_name, fill)
		for font_state in ["font_color", "font_hover_color", "font_pressed_color", "font_focus_color"]:
			button.add_theme_color_override(font_state, UITheme.CREAM if on else colour)
	line.add_theme_color_override("font_color", SAY_COLOUR if mode == "say" else DO_COLOUR)
	line.add_theme_color_override("caret_color", SAY_COLOUR if mode == "say" else DO_COLOUR)
	line.placeholder_text = _placeholder()
	_show_preview()


## The mode that fits who you're facing, unless you picked one yourself.
func _default_mode() -> void:
	if not mode_chosen:
		set_mode("say" if _is_person(target) or face_to_face() else "do")


## Under the line: exactly how it will be taken, or what this mode is for.
func _show_preview() -> void:
	if hint == null or waiting or round_playing or encounter_over:
		return
	var text := line.text.strip_edges()
	var colour: Color = SAY_COLOUR if mode == "say" else DO_COLOUR
	hint.add_theme_color_override("font_color", colour)
	var listener := str(ui.npc_record(target).get("name", "")) if _is_person(target) else ""
	if text.is_empty():
		hint.text = ("Words you say aloud%s.  Tab: do something instead." % (" to " + listener if listener else "")) \
			if mode == "say" else "Something you do with your hands.  Put words in “quotes” to say them too.  Tab: say something instead."
	elif mode == "say":
		hint.text = "You'll say%s: “%s”" % [(" to " + listener) if listener else "", text.trim_prefix("\"").trim_suffix("\"")]
	else:
		hint.text = "You'll do: %s" % text


func _process(delta: float) -> void:
	if not visible:
		return
	hint_clock += delta
	if waiting and not round_playing:
		wait_clock += delta
		var dots := ".".repeat(1 + int(wait_clock * 2.0) % 3)
		if face_to_face() or _is_person(target):
			var acting := PackedStringArray()
			for id in encounter_view.get("participants", [target]):
				acting.append(str(ui.npc_record(str(id)).get("name", "")))
			hint.text = "You and %s act at the same moment%s" % [" and ".join(acting), dots]
		else:
			hint.text = "%s%s  (%d s)" % [WORK_STAGES[mini(4, int(wait_clock / 2.5))], dots, int(wait_clock)]
		hint.add_theme_color_override("font_color", UITheme.ACCENT)
	elif encounter_over:
		hint.remove_theme_color_override("font_color")
		hint.text = "It's over. Esc to close, or type to carry on."
	elif not round_playing and str(_encounter().get("reason", "talk")) != "talk" and line.text.is_empty():
		hint.add_theme_color_override("font_color", UITheme.BAD)
		hint.text = "You're being dealt with: everyone acts at the same moment. Say “I give up” to surrender; Esc walks away."


func _encounter() -> Dictionary:
	var current = game.run_state.get("encounter")
	return current if typeof(current) == TYPE_DICTIONARY else {}


func _is_person(id: String) -> bool:
	return not id.is_empty() and not ui.npc_record(id).is_empty()


## Face to face with someone (now, or the encounter that just ended is still on show).
func face_to_face() -> bool:
	return not encounter_view.is_empty()


func showing_encounter() -> bool:
	return visible and face_to_face() and not encounter_over


## Open the bar: addressing a person, pointing at a thing, or (no id) just you.
func open(id := "", prefill := "", playing: Dictionary = {}, with_mode := "") -> void:
	if game.run_state.is_empty() or not game.gameplay_active:
		return
	var first_open := not visible
	if first_open:
		mode_chosen = false
	var current := _encounter()
	if not current.is_empty():
		encounter_view = current
		encounter_over = false
	elif _is_person(id) and not ui.npc_record(id).get("alive", true):
		ui.card.show_for(id)
		return
	elif first_open or (not id.is_empty() and id != target):
		if not encounter_over or not id.is_empty():
			encounter_view = {}
			encounter_over = false
	var people: Array = encounter_view.get("participants", [])
	if not id.is_empty():
		if _is_person(id):
			target = id
		elif id not in selected:
			if first_open:
				target = id
			selected.append(id)
	elif face_to_face() and not target in people and not people.is_empty():
		var opened_by := str(current.get("opened_by", ""))
		target = opened_by if opened_by in people else str(people[0])
	elif first_open:
		target = ""
	if first_open:
		ui.sounds.play("open")
		ui.card.hide()
		ui.hud.dismiss_hint("controls")
		show()
		if _is_person(target) and str(current.get("reason", "talk")) == "talk":
			var painted := game.get_node_or_null("NPCs/" + target + "/PaintedActor")
			if painted:
				painted.play_gesture("greet")
	if not prefill.is_empty():
		line.text = prefill
		line.caret_column = prefill.length()
	if with_mode in ["say", "do"]:
		set_mode(with_mode, true)
	render(playing)
	if playing.get("entries", []).is_empty():
		_focus_line.call_deferred()


func _focus_line() -> void:
	if visible and line.editable:
		line.grab_focus()


func close() -> void:
	if not visible:
		return
	hide()
	ui.sounds.play("close")
	target = ""
	selected.clear()
	encounter_view = {}
	encounter_over = false
	line.text = ""
	line.release_focus()


## Esc or ×: face to face this is walking away (a round of its own); otherwise it just closes.
func escape() -> void:
	if round_playing or waiting or game.request_busy:
		return
	if showing_encounter() and not _encounter().is_empty():
		game.encounter_act("leave", "", "")
		return
	close()


func _on_line_key(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE:
		line.accept_event()
		escape()
	elif event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_TAB:
		line.accept_event() # Tab flips Say / Do instead of moving focus (D-55).
		set_mode("do" if mode == "say" else "say", true)


func submit() -> void:
	var text := line.text.strip_edges()
	if text.is_empty() or waiting or round_playing or game.request_busy:
		return
	if encounter_over: # A new start after the last encounter ended.
		encounter_view = {}
		encounter_over = false
	last_text = text
	line.text = ""
	var addressed := target if _is_person(target) else ""
	var pointed := selected.duplicate()
	if not target.is_empty() and not _is_person(target) and target not in pointed:
		pointed.append(target)
	game.act(text, addressed, pointed, mode)


## While the world works out what happens: your line shows at once, the rest waits.
func wait(text: String) -> void:
	waiting = true
	wait_clock = 0.0
	line.editable = false
	if is_instance_valid(pending):
		pending.queue_free()
	pending = _line(("[color=#%s]You say: “%s”[/color]" if mode == "say" else "[color=#%s][i]You: %s[/i][/color]")
		% [(SAY_COLOUR if mode == "say" else DO_COLOUR).to_html(false), esc(text.trim_prefix("\"").trim_suffix("\""))])
	log_box.add_child(pending)
	_scroll_to_end.call_deferred()


func _ready_again() -> void:
	waiting = false
	line.editable = true
	if is_instance_valid(pending):
		pending.queue_free()
	_focus_line.call_deferred()


## Something went wrong or nobody heard: say so honestly and give the words back to edit.
func problem(text: String) -> void:
	_ready_again()
	ui.sounds.play("error")
	if line.text.is_empty():
		line.text = last_text
		line.caret_column = last_text.length()
	own_log.append({"kind": "note", "text": text, "tone": "bad"})
	if not visible:
		show()
	render()


func note(text: String) -> void:
	_ready_again()
	own_log.append({"kind": "note", "text": text})
	render()


## An attempt outside a face-to-face finished: its result goes in the log.
func result(entry: Dictionary, trace) -> void:
	_ready_again()
	selected.clear()
	if not target.is_empty() and not _is_person(target) and not game.run_state.get("objects", {}).has(target):
		target = ""
	own_log.append({"kind": "result", "entry": entry, "trace": trace, "intent": last_intent})
	while own_log.size() > 12:
		own_log.pop_front()
	if not visible:
		show()
	render()


## The encounter has finished (they left, you walked away, the gate opened): show the last round.
func ended(playing: Dictionary = {}) -> void:
	if visible and not face_to_face() and not playing.get("entries", []).is_empty():
		# A round that began and ended an encounter at once (they answered and walked off).
		encounter_view = {"participants": [target] if _is_person(target) else [], "log": []}
	if visible and face_to_face() and not encounter_over:
		encounter_over = true
		var log: Array = encounter_view.get("log", []).duplicate()
		for entry in playing.get("entries", []): # The last round happened after the encounter we last saw.
			if not entry in log:
				log.append(entry)
		encounter_view = encounter_view.duplicate()
		encounter_view["log"] = log
		_ready_again()
		render(playing)
	elif not playing.is_empty():
		_ready_again()
		game.round_played()


func address(id: String) -> void:
	target = id
	render()
	_focus_line.call_deferred()


## Point at a thing: its name goes into the line and it's sent along as something you mean.
func add_reference(id: String) -> void:
	var name := ""
	if _is_person(id):
		name = str(ui.npc_record(id).name)
	else:
		var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
		if obj.is_empty():
			return
		name = "the " + str(obj.name)
		if id not in selected:
			selected.append(id)
	if not name in line.text:
		line.text += ("" if line.text.is_empty() or line.text.ends_with(" ") else " ") + name + " "
	line.caret_column = line.text.length()
	render_chips()
	_focus_line.call_deferred()


func render(playing: Dictionary = {}) -> void:
	_render_header()
	render_chips()
	for child in log_box.get_children():
		log_box.remove_child(child)
		child.queue_free()
	pending = null
	var hidden: Array = []
	if face_to_face():
		hidden = _render_encounter(playing)
	else:
		_render_alone()
	close_button.text = "✕  Walk away" if showing_encounter() and not _encounter().is_empty() else "✕  Close"
	_default_mode()
	line.placeholder_text = _placeholder()
	_show_preview()
	if not hidden.is_empty():
		_play_lines(hidden)
	else:
		_scroll_to_end.call_deferred()


func _placeholder() -> String:
	var obj: Dictionary = game.run_state.get("objects", {}).get(target, {})
	if mode == "say":
		return ("Say something to %s…" % ui.npc_record(target).name) if _is_person(target) else "Say something…"
	if not obj.is_empty():
		return "Do something with the %s…" % obj.name
	return "Do something…  (e.g. show Hessa the gourd, lever the beam up)"


func _render_header() -> void:
	for child in tabs.get_children():
		tabs.remove_child(child)
		child.queue_free()
	var people: Array = encounter_view.get("participants", []) if face_to_face() else []
	if people.size() > 1:
		for id in people:
			var tab: Button = ui.button(str(ui.npc_record(str(id)).get("name", "?")), address.bind(str(id)), "Chip")
			tab.toggle_mode = true
			tab.button_pressed = str(id) == target
			tabs.add_child(tab)
	intent_tag.text = ""
	if game.run_state.get("mode", "") == "developer" and not last_intent.is_empty():
		intent_tag.text = "heard as %s (%s)" % [last_intent.get("kind", "?"), last_intent.get("how", "?")]
	portrait.texture = portrait_for(target)
	if _is_person(target):
		var npc: Dictionary = ui.npc_record(target)
		who.text = str(npc.name)
		var health := float(npc.get("health", 100))
		var words := PackedStringArray([str(npc.get("role", "")).to_lower()])
		words.append("dead" if not npc.get("alive", true) else "unhurt" if health >= 100 else
			"wounded" if health > 30 else "badly wounded")
		what.text = "  ·  ".join(words)
	elif game.run_state.get("objects", {}).has(target):
		var obj: Dictionary = game.run_state.objects[target]
		who.text = str(obj.name).capitalize()
		var owner: String = game.owner_name(obj)
		what.text = ("%s's" % owner) if not owner.is_empty() and owner != "you" else ("yours" if owner == "you" else "")
	else:
		who.text = "You"
		what.text = "a stranger out of time"


## A head-and-shoulders crop of someone's painted turnaround (the front view), or the thing itself.
func portrait_for(id: String) -> Texture2D:
	var actor := "traveler"
	if _is_person(id):
		actor = str(ui.npc_record(id).name).to_lower()
	elif game.run_state.get("objects", {}).has(id):
		var art: Texture2D = game.texture_for(game.run_state.objects[id])
		if art:
			return art
	var atlas: Texture2D = PaintedActor.TRAVELER
	if actor == "hessa":
		atlas = PaintedActor.HESSA
	elif PaintedActor.CAST_ART.has(actor):
		atlas = PaintedActor.CAST_ART[actor]
	else:
		actor = "traveler"
	var bounds: Rect2i = PaintedActor.BOUNDS[actor][0]
	var crop := AtlasTexture.new()
	crop.atlas = atlas
	crop.region = Rect2(bounds.position.x, bounds.position.y, bounds.size.x, minf(bounds.size.y, bounds.size.x * 1.05))
	return crop


## The things you can point at: what you carry, then what's within reach, then people nearby.
func render_chips() -> void:
	for child in chip_box.get_children():
		chip_box.remove_child(child)
		child.queue_free()
	for obj in game.try_candidates():
		var id := str(obj.id)
		var person: bool = obj.get("person", false)
		var chip: Button = ui.button(str(obj.name) + ui.chip_note(obj), func() -> void: pass, "Chip")
		chip.toggle_mode = true
		chip.button_pressed = id in selected or (person and id == target)
		if not person:
			chip.icon = game.texture_for(obj)
			chip.expand_icon = false
		else:
			chip.add_theme_color_override("font_color", UITheme.ACCENT)
		chip.toggled.connect(_on_chip.bind(id, person))
		chip_box.add_child(chip)


func _on_chip(pressed: bool, id: String, person: bool) -> void:
	if person:
		if pressed:
			address(id)
		return
	if pressed:
		add_reference(id)
	else:
		selected.erase(id)
	_focus_line.call_deferred()


func _render_alone() -> void:
	if _is_person(target):
		var npc: Dictionary = ui.npc_record(target)
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		for turn in their_mind.get("talk", []): # Earlier conversations with this person.
			log_box.add_child(_speech(turn.who == "stranger", str(npc.name), str(turn.text), true))
		if their_mind.get("talk", []).is_empty():
			log_box.add_child(_line("[i]%s looks you over.[/i]" % esc(str(npc.name))))
	if own_log.is_empty() and not _is_person(target):
		log_box.add_child(_line("[i]Choose [b]SAY[/b] for words or [b]DO[/b] for actions (Tab switches), then type in your own words. Click people and things, here or in the world, to mention them; drag things from your pack onto them.[/i]"))
	for item in own_log.slice(-8):
		match str(item.kind):
			"result":
				log_box.add_child(result_node(item.entry, item.trace))
			"note":
				var colour: Color = UITheme.BAD if item.get("tone", "") == "bad" else UITheme.INK_SOFT
				log_box.add_child(_line("[i][color=#%s]%s[/color][/i]" % [colour.to_html(false), esc(str(item.text))]))


## Draw the encounter log; the lines of the round being played back start hidden.
func _render_encounter(playing: Dictionary) -> Array:
	var log: Array = encounter_view.get("log", [])
	if log.is_empty():
		var npc: Dictionary = ui.npc_record(target)
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		for turn in their_mind.get("talk", []):
			log_box.add_child(_speech(turn.who == "stranger", str(npc.get("name", "")), str(turn.text), true))
		log_box.add_child(_line("[i]%s looks you over. Say something.[/i]" % esc(str(npc.get("name", "")))))
	var shown_round := -1
	var fresh: Array = playing.get("entries", [])
	var hidden: Array = []
	for entry in log:
		if int(entry.get("round", 0)) != shown_round:
			shown_round = int(entry.get("round", 0))
			var heading := Label.new()
			heading.theme_type_variation = "Caption"
			heading.text = "ROUND %d" % shown_round
			log_box.add_child(heading)
		var node: Control
		if entry.get("kind") == "cue": # How someone's view of you shifted, as they show it.
			node = _line("[i][color=#%s](%s)[/color][/i]" % [UITheme.INK_SOFT.to_html(false), esc(str(entry.text))])
		else:
			var theirs := str(entry.get("who", "")) != "player"
			var colour: Color = UITheme.THEIRS if theirs else (DO_COLOUR if entry.get("kind") == "do" else SAY_COLOUR)
			var words := esc(str(entry.text))
			node = _line(("[color=#%s][i]%s[/i][/color]" if not theirs and entry.get("kind") == "do"
				else "[color=#%s]%s[/color]") % [colour.to_html(false), words])
		log_box.add_child(node)
		if entry in fresh:
			node.visible = false
			hidden.append([node, entry])
			if str(entry.get("who", "")) == "player" and entry.get("kind") == "do" and not game.played_action.is_empty():
				var card := result_node(game.played_action, game.last_trace, true)
				card.visible = false
				log_box.add_child(card)
				hidden.append([card, {}])
	if encounter_over:
		var closing := _line("[i]It's over.[/i]" if game.run_state["player"].get("alive", true) else "")
		log_box.add_child(closing)
		if not hidden.is_empty():
			closing.visible = false
			hidden.append([closing, {}])
	return hidden


## Play a round back: each line appears in turn with its moment in the world.
func _play_lines(lines: Array) -> void:
	round_playing = true
	line.editable = false
	for pair in lines:
		await get_tree().create_timer(0.45).timeout
		if not is_instance_valid(pair[0]):
			break
		pair[0].visible = true
		if not pair[1].is_empty():
			game.round_beat(pair[1])
		_scroll_to_end()
	round_playing = false
	waiting = false
	line.editable = true
	_scroll_to_end()
	_focus_line()
	game.round_played()


func _scroll_to_end() -> void:
	await get_tree().process_frame
	if is_instance_valid(scroll):
		scroll.scroll_vertical = int(scroll.get_v_scroll_bar().max_value)


static func esc(text: String) -> String:
	return text.replace("[", "[lb]")


func _line(bbcode: String) -> RichTextLabel:
	var node := RichTextLabel.new()
	node.bbcode_enabled = true
	node.fit_content = true
	node.scroll_active = false
	node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	node.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	node.mouse_filter = Control.MOUSE_FILTER_IGNORE
	node.text = bbcode
	return node


func _speech(mine: bool, their_name: String, text: String, faded: bool) -> RichTextLabel:
	var node := _line(("[b]You:[/b] “%s”" % esc(text)) if mine else
		"[color=#%s][b]%s:[/b] “%s”[/color]" % [UITheme.THEIRS.to_html(false), esc(their_name), esc(text)])
	if faded:
		node.modulate.a = 0.6
	return node


## One attempt's result, inline: what happened, what changed, anything made (with its picture).
func result_node(entry: Dictionary, trace, compact := false) -> VBoxContainer:
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 2)
	box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var category := str(entry.get("category", ""))
	var tone: Color = UITheme.GOOD if category in ["success", "partial_success"] else \
		UITheme.BAD if category in ["failed", "blocked", "unsupported"] else UITheme.ACCENT
	if not compact:
		box.add_child(_line("[b][color=#%s]%s[/color][/b]   [i][color=#%s]“%s”[/color][/i]" % [
			tone.to_html(false), esc(ui.result_title(entry)), UITheme.INK_SOFT.to_html(false), esc(str(entry.get("text", "")))]))
	box.add_child(_line(esc(str(entry.get("reason", "")))))
	for sentence in ui.result_details(entry):
		box.add_child(_line("[color=#%s]%s[/color]" % [UITheme.ACCENT.to_html(false), esc(sentence)]))
	for id in ui.result_objects(entry):
		box.add_child(_thing_row(str(id)))
	if game.run_state.get("mode", "") == "developer" and typeof(trace) == TYPE_DICTIONARY and not compact:
		var details := VBoxContainer.new()
		details.visible = false
		var toggle: Button = ui.button("Details", func() -> void: pass, "Quiet")
		toggle.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		toggle.pressed.connect(func() -> void:
			if details.get_child_count() == 0:
				ui.trace_view(details, trace)
			details.visible = not details.visible)
		box.add_child(toggle)
		box.add_child(details)
	box.add_child(HSeparator.new())
	return box


## A thing an attempt made, took or cut: picture, name, weight, where it is.
func _thing_row(id: String) -> Control:
	var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	if obj.is_empty():
		return row
	row.add_child(ui.object_icon(obj, 52))
	var made: bool = obj.get("created_by") == "player"
	var where := "in your pack" if obj.get("holder_id") == "player" else \
		("too heavy to carry" if not "carry" in obj.get("capabilities", []) else "on the ground")
	var text := "[b]%s[/b]  ·  %s kg  ·  %s" % [esc(str(obj.name).capitalize()), obj.mass_kg, where]
	if made:
		text += "\n[color=#%s]Made of %s.[/color]" % [UITheme.INK_SOFT.to_html(false), esc(", ".join(obj.get("materials", [])))]
		var abilities := PackedStringArray()
		for capability in obj.get("known_capabilities", []):
			abilities.append(str(capability.text) + str(ui.CAPABILITY_NOTES.get(str(capability.status), "")))
		if not abilities.is_empty():
			text += "\n[i]" + esc("; ".join(abilities)) + "[/i]"
	var words := _line(text)
	row.add_child(words)
	row.set_meta("object_id", id)
	row.mouse_filter = Control.MOUSE_FILTER_STOP
	row.tooltip_text = "Right-click to look closer"
	row.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_RIGHT:
			ui.card.show_for(id))
	return row
