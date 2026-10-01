extends PanelContainer
## Right-click on anything: a parchment card beside the cursor with what you can see of it
## (GDD §3 Inspect). It closes with Esc or a click anywhere else.

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var ui: Control
var game: Node2D
var shown_id := ""
var body: VBoxContainer


func build(owner_ui: Control, owner_game: Node2D) -> void:
	ui = owner_ui
	game = owner_game
	custom_minimum_size.x = 360
	body = VBoxContainer.new()
	body.add_theme_constant_override("separation", 6)
	add_child(body)
	hide()


func _input(event: InputEvent) -> void:
	# A click anywhere outside the card closes it (the click still does whatever it does).
	if visible and event is InputEventMouseButton and event.pressed \
			and not Rect2(Vector2.ZERO, size).has_point(get_local_mouse_position()):
		hide()


func show_for(id: String, _at = null) -> void:
	for child in body.get_children():
		body.remove_child(child)
		child.queue_free()
	shown_id = id
	var npc: Dictionary = ui.npc_record(id)
	var obj: Dictionary = game.run_state.get("objects", {}).get(id, {})
	if npc.is_empty() and obj.is_empty():
		hide()
		return
	if npc.is_empty():
		_object(obj)
	else:
		_person(npc)
	ui.sounds.play("open")
	show()
	ui.guide.report("inspect") # The tutorial's "look closer" (D-52).
	size = Vector2.ZERO
	reset_size()
	var parent := get_parent() as Control
	var at := parent.get_local_mouse_position() + Vector2(18, -40)
	if _at == null and ui.bar.visible:
		at.y = minf(at.y, parent.size.y - ui.bar.size.y - size.y - 16)
	position = Vector2(clampf(at.x, 8, parent.size.x - size.x - 8), clampf(at.y, 8, parent.size.y - size.y - 8))
	_place.call_deferred()


func _place() -> void:
	await get_tree().process_frame # Wrapped text knows its height only after one layout pass.
	size = Vector2.ZERO
	reset_size()
	var parent := get_parent() as Control
	position = Vector2(clampf(position.x, 8, parent.size.x - size.x - 8), clampf(position.y, 8, parent.size.y - size.y - 8))


func _header(picture: Texture2D, title: String, subtitle: String, missing := false) -> void:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	body.add_child(row)
	var frame := PanelContainer.new()
	frame.theme_type_variation = "SlotPanel"
	frame.custom_minimum_size = Vector2(76, 76)
	row.add_child(frame)
	var icon := UITheme.picture(picture)
	frame.add_child(icon)
	if picture == null:
		var waiting := preload("res://scripts/loading_icon.gd").new()
		waiting.missing = missing
		icon.add_child(waiting)
	var words := VBoxContainer.new()
	words.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	words.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_child(words)
	var name_label := Label.new()
	name_label.theme_type_variation = "Heading"
	name_label.text = title
	name_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	name_label.custom_minimum_size.x = 240
	words.add_child(name_label)
	if not subtitle.is_empty():
		var sub := Label.new()
		sub.theme_type_variation = "Small"
		sub.text = subtitle
		sub.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		sub.custom_minimum_size.x = 240
		words.add_child(sub)


func _text(text: String, variation := "") -> Label:
	var node := Label.new()
	node.text = text
	node.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	node.custom_minimum_size.x = 320
	node.add_theme_font_size_override("font_size", 15)
	if not variation.is_empty():
		node.theme_type_variation = variation
	body.add_child(node)
	return node


func _object(obj: Dictionary) -> void:
	var owner: String = game.actions.owner_name(obj)
	var belongs := "Yours" if owner == "you" else ("Nobody's" if owner.is_empty() else owner + "'s")
	if obj.get("lent_to") == "player":
		belongs += ", lent to you"
	var where := "In your pack" if obj.get("holder_id") == "player" else "Lying here"
	_header(game.art.texture_for(obj), str(obj.name).capitalize(), "%s  ·  %s" % [belongs, where],
		game.art.sprite_status(obj) in ["failed", "none"])
	if not str(obj.get("description", "")).is_empty():
		_text(str(obj.description))
	var facts := PackedStringArray(["%s kg" % obj.mass_kg, str(obj.get("condition", "usable")).capitalize()])
	if obj.get("length_m") != null:
		facts.append("about %s m long" % obj.length_m)
	if float(obj.get("capacity_l", 0)) > 0:
		facts.append("water %s of %s l" % [obj.get("water_l", 0), obj.capacity_l])
	_text("  ·  ".join(facts), "Small")
	if not obj.get("materials", []).is_empty():
		_text("Made of " + ", ".join(obj.materials) + ".")
	var feel: String = ui.flag_words(obj.get("flags", []))
	if not feel.is_empty():
		_text("Qualities: " + feel + ".")
	if obj.get("created_by") == "player":
		_text(ui.provenance(obj)).add_theme_color_override("font_color", UITheme.ACCENT)
		for capability in obj.get("known_capabilities", []):
			_text("• " + str(capability.text) + str(ui.CAPABILITY_NOTES.get(str(capability.status), "")))
		if game.art.is_placeholder(obj):
			_text("Its picture is still being painted." if game.art.sprite_status(obj) == "polling"
				else "Its picture couldn't be painted; a stand-in is shown.", "Small")
	if obj.get("readable") != null:
		var read: Button = ui.button("Read it", func() -> void: ui.open_book(obj))
		read.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
		body.add_child(read)
	var hover: Dictionary = ui.cursor.describe(str(obj.id)) if obj.get("holder_id") == null else {}
	var hint := "Drag it onto someone or something to use it." if obj.get("holder_id") == "player" else \
		("Left-click: " + str(hover.get("verb", "")) if hover.get("reachable", false) else "Walk closer to reach it.")
	_text(hint, "Small").add_theme_color_override("font_color",
		UITheme.STEAL if hover.get("tone", "") == "steal" else UITheme.INK_SOFT)


func _person(npc: Dictionary) -> void:
	var alive: bool = npc.get("alive", true)
	var injuries: Array = npc.get("injuries", [])
	var state_word := "dead" if not alive else ("hurt" if not injuries.is_empty() else "unhurt")
	_header(ui.bar.portrait_for(str(npc.id)), str(npc.name) + ("" if alive else " (dead)"),
		"%s  ·  %s" % [str(npc.get("role", "")), state_word])
	var painted := game.get_node_or_null("NPCs/%s/PaintedActor" % npc.id)
	if painted and alive:
		painted.play_gesture("greet")
	if not alive:
		_text(str(npc.name) + " lies still on the ground." + ("\nCause: " + str(injuries[-1]) if not injuries.is_empty() else ""))
	elif not injuries.is_empty():
		_text(str(npc.name) + " is hurt: " + "; ".join(injuries) + ".")
	var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
	var known = their_mind.get("knows") if typeof(their_mind.get("knows")) == TYPE_DICTIONARY else {}
	if alive:
		var mood := str(their_mind.get("mood")) if their_mind.get("mood") != null else "at ease"
		var doing := str(their_mind.get("doing", "")) if their_mind.get("doing") != null else ""
		_text(("Seems %s" % mood) + ((", %s." % doing) if not doing.is_empty() else "."))
		var talks := int(known.get("talks", 0)) + (1 if not known.get("notes", []).is_empty() else 0)
		_text("You have not spoken yet." if talks == 0 and not their_mind.get("met", false) else
			"You have spoken once." if talks <= 1 else "You have spoken %d times." % talks, "Small")
		_text("Left-click to talk.", "Small")
	if game.run_state.get("mode", "") == "developer" and not their_mind.is_empty():
		var lines := PackedStringArray()
		for memory in their_mind.get("memories", []):
			lines.append("• (%s) %s" % [memory.source, memory.summary])
		var job = their_mind.get("job")
		var view: Dictionary = their_mind.get("regard", {})
		var episodes: Array = known.get("episodes", [])
		var feelings := PackedStringArray()
		var views = their_mind.get("opinions") if typeof(their_mind.get("opinions")) == TYPE_DICTIONARY else {}
		for other_id in views:
			feelings.append("%s %+.2f" % [str(ui.npc_record(str(other_id)).get("name", other_id)), float(views[other_id].warmth)])
		_text("DEVELOPER  ·  knows the stranger as %s · %d episodes%s\nOpinions: %s" % [
			str(known.get("name") if known.get("name") != null else known.get("heard_name", "-")), episodes.size(),
			("\nLast: " + str(episodes[-1].text)) if not episodes.is_empty() else "", ", ".join(feelings)], "Small")
		_text("DEVELOPER  ·  fear %s · anger %s · trust %s · suspicion %s · doing: %s\n%s" % [
			their_mind.get("feelings", {}).get("fear", 0), their_mind.get("feelings", {}).get("anger", 0),
			view.get("trust", "-"), view.get("suspicion", "-"),
			str(job.kind) if typeof(job) == TYPE_DICTIONARY else "routine",
			"\n".join(lines) if not lines.is_empty() else "No memories of the stranger."], "Small")
