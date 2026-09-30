extends Control
## The game layers (GDD D-55): what makes progress visible. Toasts (top right) when someone's standing toward you
## changes, when you achieve a deed (deeds.gd) and when word of you spreads; a reveal card when you make something;
## and a marker (a ring over them, an arrow at the screen's edge when they're out of sight) on the person your
## pinned goal is about. Everything is read from the state after each change: nothing here decides anything.

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const Deeds := preload("res://scripts/ui/deeds.gd")
const GLOW := Color(0.95, 0.82, 0.45)

var ui: Control
var game: Node2D
var toasts: VBoxContainer
var reveal: PanelContainer
var reveal_icon: Control # Holds the made thing's picture (or "Painting…" until its art arrives).
var reveal_title: Label
var reveal_text: Label
var arrow: Control
var ring: Node2D
var run_id := ""
var seen_standing := {}
var seen_deeds := {}
var seen_made := {}
var seen_tellers := {}
var pinned := "" # The pinned lead's text, this journey (the goal tracker and the marker follow it).


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	arrow = Control.new()
	arrow.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	arrow.mouse_filter = Control.MOUSE_FILTER_IGNORE
	arrow.draw.connect(_draw_arrow)
	add_child(arrow)
	toasts = VBoxContainer.new()
	toasts.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	toasts.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	toasts.offset_right = -16
	toasts.offset_top = 62
	toasts.custom_minimum_size.x = 330
	toasts.add_theme_constant_override("separation", 8)
	toasts.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(toasts)
	_build_reveal()
	ring = preload("res://scripts/ui/tutorial_focus.gd").new()
	ring.hide()
	game.add_child(ring)


func _build_reveal() -> void:
	reveal = PanelContainer.new()
	reveal.theme_type_variation = "PaperPanel"
	reveal.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	reveal.grow_horizontal = Control.GROW_DIRECTION_BOTH
	reveal.offset_top = 90
	reveal.mouse_filter = Control.MOUSE_FILTER_STOP
	reveal.gui_input.connect(func(event: InputEvent) -> void:
		if event is InputEventMouseButton and event.pressed:
			reveal.hide())
	add_child(reveal)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	reveal.add_child(row)
	reveal_icon = CenterContainer.new()
	reveal_icon.custom_minimum_size = Vector2(112, 112)
	row.add_child(reveal_icon)
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.custom_minimum_size.x = 340
	row.add_child(column)
	var kicker := Label.new()
	kicker.text = "NEW  ·  MADE BY YOU"
	kicker.theme_type_variation = "Caption"
	kicker.add_theme_color_override("font_color", UITheme.GOOD)
	column.add_child(kicker)
	reveal_title = Label.new()
	reveal_title.add_theme_font_override("font", UITheme.serif(true))
	reveal_title.add_theme_font_size_override("font_size", 26)
	reveal_title.add_theme_color_override("font_color", UITheme.ACCENT)
	column.add_child(reveal_title)
	reveal_text = Label.new()
	reveal_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	reveal_text.custom_minimum_size.x = 340
	reveal_text.add_theme_font_size_override("font_size", 15)
	column.add_child(reveal_text)
	reveal.hide()


## After every new state: toasts for what changed, the reveal card for anything new you made.
func refresh() -> void:
	var state: Dictionary = game.run_state
	if state.is_empty():
		return
	var first := str(state.get("run_id", "")) != run_id
	if first: # A new journey (or a reload): what's there already is the baseline, not news.
		run_id = str(state.get("run_id", ""))
		seen_standing.clear()
		seen_made.clear()
		seen_tellers.clear()
		seen_deeds = _load_seen()
		pinned = _load_pin()
	for npc in state.get("npcs", []):
		var id := str(npc.id)
		var now := Deeds.standing_word(npc)
		var before := str(seen_standing.get(id, ""))
		if not first and not before.is_empty() and before != now and now != "unknown":
			var warmer := Deeds.STANDING_ORDER.find(now) > Deeds.STANDING_ORDER.find(before)
			var mark := "·" if before == "unknown" else "▲" if warmer else "▼"
			_toast(ui.bar.portrait_for(id), "%s  %s  %s" % [npc.name, mark, Deeds.STANDING_WORDS.get(now, now)],
				str(Deeds.STANDING_BEFORE.get(before, "")), Deeds.STANDING_COLOURS.get(now, UITheme.INK))
		seen_standing[id] = now
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		var job = their_mind.get("job")
		var telling := typeof(job) == TYPE_DICTIONARY and str(job.get("kind", "")) == "tell"
		if telling and not seen_tellers.has(id) and not first:
			var other := str(ui.npc_record(str(job.get("target", ""))).get("name", "someone"))
			_toast(ui.bar.portrait_for(id), "Word is spreading", "%s is off to tell %s about you." % [npc.name, other],
				UITheme.ACCENT)
		if telling:
			seen_tellers[id] = true
		else:
			seen_tellers.erase(id)
	var fresh_deeds := false
	for deed in Deeds.compute(state):
		if seen_deeds.has(deed.id):
			continue
		seen_deeds[deed.id] = true
		fresh_deeds = true
		if first or deed.id.begins_with("news:"):
			continue # News already had its own toast.
		_toast(ui.bar.portrait_for(str(deed.who)) if not str(deed.who).is_empty() else null, "★  " + str(deed.title),
			str(deed.text), Color("9a6a12"), "deed")
	if fresh_deeds:
		_save_seen()
	for obj in state.get("objects", {}).values():
		if obj.get("created_by") != "player" or seen_made.has(str(obj.id)):
			continue
		seen_made[str(obj.id)] = true
		if not first:
			_reveal(obj)


func _toast(icon: Texture2D, title: String, text: String, colour: Color, sound := "toast") -> void:
	while toasts.get_child_count() >= 3:
		var oldest := toasts.get_child(0)
		toasts.remove_child(oldest)
		oldest.queue_free()
	var card := PanelContainer.new()
	card.theme_type_variation = "PaperPanel"
	card.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	card.add_child(row)
	if icon:
		var picture := TextureRect.new()
		picture.texture = icon
		picture.custom_minimum_size = Vector2(44, 44)
		picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		row.add_child(picture)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 0)
	column.custom_minimum_size.x = 250
	row.add_child(column)
	var heading := Label.new()
	heading.text = title
	heading.add_theme_font_override("font", UITheme.serif(true))
	heading.add_theme_font_size_override("font_size", 16)
	heading.add_theme_color_override("font_color", colour)
	column.add_child(heading)
	var words := Label.new()
	words.text = text
	words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	words.add_theme_font_size_override("font_size", 13)
	column.add_child(words)
	toasts.add_child(card)
	ui.sounds.play(sound)
	card.modulate.a = 0.0
	var fade := card.create_tween()
	fade.tween_property(card, "modulate:a", 1.0, 0.25)
	fade.tween_interval(5.5)
	fade.tween_property(card, "modulate:a", 0.0, 0.8)
	fade.tween_callback(card.queue_free)


## Something you made, shown off for a moment (click to dismiss).
func _reveal(obj: Dictionary) -> void:
	for old in reveal_icon.get_children():
		reveal_icon.remove_child(old)
		old.queue_free()
	reveal_icon.add_child(ui.object_icon(obj, 112))
	reveal_title.text = str(obj.name).capitalize()
	var words := PackedStringArray()
	if not str(obj.get("description", "")).is_empty():
		words.append(str(obj.description))
	var use: String = ui.gear_words(obj)
	if not use.is_empty():
		words.append(use)
	reveal_text.text = "\n".join(words)
	reveal.show()
	reveal.modulate.a = 0.0
	reveal.scale = Vector2(0.92, 0.92)
	ui.sounds.play("success")
	var show := reveal.create_tween().set_parallel(true)
	show.tween_property(reveal, "modulate:a", 1.0, 0.25)
	show.tween_property(reveal, "scale", Vector2.ONE, 0.25).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	var hide := reveal.create_tween()
	hide.tween_interval(4.0)
	hide.tween_property(reveal, "modulate:a", 0.0, 0.6)
	hide.tween_callback(reveal.hide)


# --- The pinned goal ------------------------------------------------------------------------------------------

## The lead a claim is about, and who: a referral's target, else whoever told you.
static func lead_person(claim: Dictionary) -> String:
	return str(claim.refer) if claim.get("refer") != null else str(claim.get("npc_id", ""))


func pin(lead: String) -> void:
	pinned = "" if pinned == lead else lead
	var file := ConfigFile.new()
	file.load("user://pins.cfg")
	file.set_value("pins", run_id, pinned)
	file.save("user://pins.cfg")
	ui.hud.refresh()


func pinned_claim() -> Dictionary:
	if pinned.is_empty():
		return {}
	for claim in game.run_state.get("learned", []):
		if str(claim.get("lead", "")) == pinned:
			return claim
	return {}


func _process(_delta: float) -> void:
	if game == null or game.run_state.is_empty():
		ring.hide()
		return
	var claim := pinned_claim()
	var person := lead_person(claim) if not claim.is_empty() else ""
	var actor := game.get_node_or_null("NPCs/" + person) as Node2D if not person.is_empty() else null
	var guided: bool = ui.guide.active()
	var near: bool = actor != null and actor.position.distance_to(game.player.position) < 3.0 * game.CELL
	ring.visible = actor != null and not guided and not near and not ui.blocks_movement()
	if ring.visible:
		ring.position = actor.position
	arrow.queue_redraw()


func _draw_arrow() -> void:
	if not ring.visible:
		return
	var screen: Vector2 = game.get_viewport().get_canvas_transform() * ring.position
	var view := get_viewport_rect().size
	var margin := 48.0
	if Rect2(Vector2(margin, margin), view - Vector2(margin, margin) * 2).has_point(screen):
		return
	var toward := (screen - view * 0.5).normalized()
	var edge := Vector2(clampf(screen.x, margin, view.x - margin), clampf(screen.y, margin + 60, view.y - margin - 90))
	var local: Vector2 = (edge - ui.root.position) / ui.ui_scale
	var tip: Vector2 = local + toward * 18.0
	var side := toward.orthogonal() * 14.0
	var shape := PackedVector2Array([tip, local - toward * 12.0 + side, local - toward * 12.0 - side])
	arrow.draw_colored_polygon(shape, Color(GLOW, 0.75 + 0.25 * sin(Time.get_ticks_msec() / 200.0)))
	arrow.draw_polyline(shape + PackedVector2Array([shape[0]]), Color(0.2, 0.12, 0.04), 2.0, true)


func _load_pin() -> String:
	var file := ConfigFile.new()
	return str(file.get_value("pins", run_id, "")) if file.load("user://pins.cfg") == OK else ""


func _load_seen() -> Dictionary:
	var file := FileAccess.open("user://deeds/%s.json" % run_id, FileAccess.READ)
	if file == null:
		return {}
	var data = JSON.parse_string(file.get_as_text())
	var seen := {}
	for id in (data if typeof(data) == TYPE_ARRAY else []):
		seen[str(id)] = true
	return seen


func _save_seen() -> void:
	DirAccess.make_dir_recursive_absolute("user://deeds")
	var file := FileAccess.open("user://deeds/%s.json" % run_id, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(seen_deeds.keys()))
