extends Node
## What the world shows of the journey's state: people walking and turning, speech bubbles, things
## falling and appearing, the gate, and what changed between two states played out on screen.

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var game: Node2D # The game (scripts/main.gd), whose child this is.


var npc_targets: Dictionary = {}


var npc_facing: Dictionary = {}


var warm_until: Dictionary = {} # npc id -> seconds: show a warm mark over their head until then.


var shown_speech: Dictionary = {} # npc id -> key of the last line shown in a bubble


var shown_cues: Dictionary = {} # npc id -> key of the last regard cue shown


func spawn_people() -> void:
	var old := game.get_node_or_null("NPCs")
	if old:
		game.remove_child(old)
		old.queue_free()
	var group := Node2D.new()
	group.name = "NPCs"
	group.y_sort_enabled = true
	game.add_child(group)
	npc_targets.clear()
	npc_facing.clear()
	for npc in game.run_state["npcs"]:
		var actor := Node2D.new()
		actor.name = str(npc["id"])
		actor.position = game.cell_center(int(npc["x"]), int(npc["y"]))
		group.add_child(actor)
		var presence := preload("res://scripts/actor_presence.gd").new()
		actor.add_child(presence)
		var painted := preload("res://scenes/painted_actor.tscn").instantiate()
		painted.name = "PaintedActor"
		painted.actor_id = str(npc["name"]).to_lower()
		actor.add_child(painted)
		if not npc.get("alive", true):
			painted.lie_dead()
		elif npc.get("down", false):
			painted.knock_down(1.0, true)
		npc_targets[str(npc["id"])] = actor.position
		npc_facing[str(npc["id"])] = 0
		var said = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("said")
		shown_speech[str(npc["id"])] = str(said.key) if typeof(said) == TYPE_DICTIONARY else ""
		var cue = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("cue")
		shown_cues[str(npc["id"])] = str(cue.key) if typeof(cue) == TYPE_DICTIONARY else ""
		var status := preload("res://scripts/ui/head_status.gd").new()
		status.name = "Status"
		status.game = game
		status.npc_id = str(npc["id"])
		status.position = Vector2(0, -126)
		actor.add_child(status)
		var nameplate := Label.new()
		nameplate.name = "Nameplate"
		nameplate.text = str(npc["name"])
		nameplate.modulate.a = 0.0
		nameplate.position = Vector2(-30, -115)
		nameplate.add_theme_font_size_override("font_size", 13)
		nameplate.add_theme_color_override("font_color", Color("fff0cf"))
		nameplate.add_theme_color_override("font_shadow_color", Color.BLACK)
		nameplate.add_theme_constant_override("shadow_offset_x", 1)
		nameplate.add_theme_constant_override("shadow_offset_y", 1)
		actor.add_child(nameplate)


func animate_people(delta: float) -> void:
	for npc in game.run_state.get("npcs", []):
		var id := str(npc["id"])
		var actor := game.get_node_or_null("NPCs/" + id) as Node2D
		if actor == null or not npc.get("alive", true) or npc.get("down", false):
			continue
		var target: Vector2 = npc_targets.get(id, actor.position)
		var before := actor.position
		var mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		var job = mind.get("job") if typeof(mind) == TYPE_DICTIONARY else null
		var pace := 190.0 if typeof(job) == TYPE_DICTIONARY and job.get("speed") == "run" else 90.0
		var behind := actor.position.distance_to(target)
		actor.position = actor.position.move_toward(target, (pace if behind < 128.0 else behind * 3.0) * delta)
		var travel := actor.position - before
		var painted := actor.get_node("PaintedActor")
		var facing := int(npc_facing.get(id, 0))
		var mode := "idle"
		if travel.length() > 0.05:
			facing = 3 if travel.x > 0.0 else 1 if travel.x < 0.0 else 0 if travel.y > 0.0 else 2
			npc_facing[id] = facing
			mode = "run" if travel.length() > 120.0 * delta else "walk"
		elif npc.has("controller"):
			mode = str(npc["controller"].get("activity", "idle"))
			if mode == "wait":
				mode = "idle"
			var chatting = mind.get("chatting_with") if typeof(mind) == TYPE_DICTIONARY else null
			if typeof(chatting) == TYPE_DICTIONARY and float(chatting.get("until", 0)) > float(game.run_state.get("sim_time_ms", 0)):
				var partner := game.get_node_or_null("NPCs/" + str(chatting.id)) as Node2D
				if partner: # Two people talking turn to face each other.
					var across := partner.position - actor.position
					facing = _toward(across)
					npc_facing[id] = facing
					mode = "idle"
			if typeof(mind) == TYPE_DICTIONARY and mind.get("facing_player", false):
				# Wary people turn to face the stranger (decided by code on the server, not by a model).
				var toward: Vector2 = game.player.position - actor.position
				facing = _toward(toward)
				npc_facing[id] = facing
		painted.set_motion(facing, mode, travel.length(), delta)


## Which way someone faces to look along this (0 down, 1 left, 2 up, 3 right).
func _toward(along: Vector2) -> int:
	return (3 if along.x > 0.0 else 1) if absf(along.x) > absf(along.y) else (0 if along.y > 0.0 else 2)


## Collisions from the map's data (data/maps), the same rectangles the server treats as solid.
func apply_building_geometry(map_id := "village") -> void:
	var file_name := "res://data/maps/%s.json" % map_id
	var geometry = JSON.parse_string(FileAccess.get_file_as_string(file_name))
	if typeof(geometry) != TYPE_DICTIONARY:
		push_error("Could not load the map: " + file_name)
		return
	var holder := game.get_node_or_null("BuildingCollision")
	if holder == null: # A map scene may leave its collisions to the data: they're made here.
		holder = Node2D.new()
		holder.name = "BuildingCollision"
		game.add_child(holder)
		game.map_parts.append(holder)
	for item in geometry["buildings"] + geometry["obstacles"]:
		var body := holder.get_node_or_null(str(item["name"])) as StaticBody2D
		if body == null:
			body = StaticBody2D.new()
			body.name = str(item["name"])
			var made := CollisionShape2D.new()
			made.name = "CollisionShape2D"
			body.add_child(made)
			holder.add_child(body)
		var cells: Array = item["cells"]
		var shape_node := body.get_node("CollisionShape2D") as CollisionShape2D
		var rectangle := RectangleShape2D.new()
		rectangle.size = Vector2(float(cells[2]), float(cells[3])) * game.CELL
		shape_node.shape = rectangle
		shape_node.set_deferred("disabled", false)
		body.position = Vector2(float(cells[0]) + float(cells[2]) * 0.5,
			float(cells[1]) + float(cells[3]) * 0.5) * game.CELL
	if geometry.get("gate") != null and game.gate_shape == null: # A gate in the data but not in the scene.
		var gate: Dictionary = geometry["gate"]
		var closed := StaticBody2D.new()
		closed.name = "ClosedGate"
		var shape := CollisionShape2D.new()
		var box := RectangleShape2D.new()
		var wide := float(gate.cols[1]) - float(gate.cols[0]) + 1.0
		var gap := Vector2(wide, float(gate.rows[1]) - float(gate.rows[0]) + 1.0)
		box.size = gap * game.CELL
		shape.shape = box
		closed.add_child(shape)
		closed.position = (Vector2(float(gate.cols[0]), float(gate.rows[0])) + gap * 0.5) * game.CELL
		holder.add_child(closed)
		game.gate_shape = shape


func sync() -> void:
	var started := Time.get_ticks_usec()
	_sync_now()
	game._prof("sync_display", started)


func _sync_now() -> void:
	if game.gate_shape: # A map with a gate: closed until someone opens it.
		game.gate_shape.set_deferred("disabled", bool(game.run_state["gate_open"]))
	if game.gate_sprite and game.gate_opening: # Only the village draws its gate (a field gate is just art).
		game.gate_sprite.visible = not bool(game.run_state["gate_open"])
		game.gate_opening.visible = bool(game.run_state["gate_open"])
	for object_id in game.run_state.get("objects", {}):
		var obj: Dictionary = game.run_state["objects"][object_id]
		if obj.has("scene_node") or obj.get("no_sprite", false): # Map trees and building parts keep their authored art.
			continue
		var sprite := game.get_node_or_null("M2Objects/" + str(object_id)) as Sprite2D
		if sprite == null:
			if obj["holder_id"] != null:
				continue
			sprite = Sprite2D.new()
			sprite.name = str(object_id)
			sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			sprite.set_meta("dynamic", true)
			game.get_node("M2Objects").add_child(sprite)
		if sprite.has_meta("dynamic"):
			game.art.apply_to(sprite, obj)
		sprite.visible = obj["holder_id"] == null
		# A fire that has burnt out goes cold and grey.
		sprite.self_modulate = Color(0.45, 0.43, 0.42) if str(obj.get("condition", "usable")) == "burnt out" else Color.WHITE
		sprite.position = game.cell_center(int(obj["x"]), int(obj["y"]))
		var fixture: Dictionary = game.run_state["objects"].get(str(obj.get("installed_in", "")), {})
		if not fixture.is_empty() and not fixture.get("no_sprite", false):
			sprite.position.y -= 36.0 # Up in its fixture (a bar in its brackets), not stuck in ground art like a mire.
		_place_on_gate(sprite, obj)
	_apply_world_features()
	for npc in game.run_state.get("npcs", []):
		npc_targets[str(npc["id"])] = game.cell_center(int(npc["x"]), int(npc["y"]))
		var said = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("said")
		if typeof(said) == TYPE_DICTIONARY and shown_speech.get(str(npc["id"]), "") != str(said.key):
			shown_speech[str(npc["id"])] = str(said.key)
			var after := float(said.get("after_ms", 0)) / 1000.0 # The second speaker in a chat answers a beat later.
			if after > 0.0:
				get_tree().create_timer(after).timeout.connect(show_bubble.bind(str(npc["id"]), str(said.text)))
			else:
				show_bubble(str(npc["id"]), str(said.text))
		var cue = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("cue")
		if typeof(cue) == TYPE_DICTIONARY and shown_cues.get(str(npc["id"]), "") != str(cue.key):
			shown_cues[str(npc["id"])] = str(cue.key)
			if str(cue.get("kind", "")) in ["warmer", "trusting", "easier"]:
				warm_until[str(npc["id"])] = Time.get_ticks_msec() / 1000.0 + 3.5
			# Standing toasts (D-55) now say how someone's view of you changed; face to face, the round log shows it.
		var plate := game.get_node_or_null("NPCs/%s/Nameplate" % npc["id"]) as Label
		if plate:
			var standing: bool = npc.get("alive", true) and not npc.get("down", false)
			plate.text = str(npc["name"]) + ("" if standing else " (down)" if npc.get("alive", true) else " (dead)")
			plate.position.y = -115.0 if standing else -58.0 # Down beside a body.
			plate.reset_size()
	game.gate_button.text = "Close gate (test)" if game.run_state["gate_open"] else "Open gate (test)"
	game.trace_text.text = "RUN " + str(game.run_state["run_id"]).substr(0, 12) + "\n" \
		+ "Mode: " + str(game.run_state["mode"]) + "\n" \
		+ "Event: " + str(int(game.run_state["event_seq"])) + "\n" \
		+ "Tick: " + str(int(game.run_state["tick"])) + " (" + str(int(game.run_state["sim_time_ms"])) + " ms)\n" \
		+ "Player: (" + str(int(game.run_state["player"]["x"])) + ", " + str(int(game.run_state["player"]["y"])) + ")\n" \
		+ "Gate: " + ("open" if game.run_state["gate_open"] else "closed") + "\n" \
		+ "Objective: " + ("complete" if game.run_state["inside_city"] else "active")
	game.trace_panel.visible = game.run_state["mode"] == "developer" and game.trace_panel.visible
	game.ui.note_cell(Vector2i(int(game.run_state["player"]["x"]), int(game.run_state["player"]["y"])))
	game.ui.refresh()


## The bar across the gate is drawn big, across the gate itself; the brackets show only while empty (D-42).
func _place_on_gate(sprite: Sprite2D, obj: Dictionary) -> void:
	var on_gate := str(obj.get("installed_in", "")) == "gate_brackets"
	var brackets := str(obj.id) == "gate_brackets"
	sprite.z_index = 1 if on_gate or brackets else 0
	sprite.rotation = -0.5 if on_gate else 0.0
	if not (on_gate or brackets) or game.gate_sprite == null:
		return
	sprite.position = game.gate_sprite.position + Vector2(0, 34)
	if on_gate and sprite.texture:
		sprite.scale = Vector2.ONE * (190.0 / float(sprite.texture.get_width()))
	if brackets:
		sprite.visible = not game.run_state.get("objects", {}).values().any(
			func(o) -> bool: return str(o.get("installed_in", "")) == "gate_brackets")


## Play what happened between two states: people striking the player, the player dying.
func react_to(before: Dictionary) -> void:
	var old_journal: Array = before.get("journal", [])
	var journal: Array = game.run_state.get("journal", [])
	for index in range(old_journal.size(), journal.size()):
		var entry: Dictionary = journal[index]
		if entry.get("kind") == "npc":
			var speaker := game.get_node_or_null("NPCs/%s/PaintedActor" % entry.npc_id)
			if speaker:
				speaker.play_gesture("gesture") # A gesture as they speak.
		if entry.get("kind") == "npc_attack":
			var striker := game.get_node_or_null("NPCs/%s/PaintedActor" % entry.npc_id)
			if striker:
				striker.play_gesture("gesture")
			if entry.result != "missed" and game.run_state["player"].get("alive", true):
				game.player_visual.hurt(1.0)
				game.shake_camera()
			game.ui.notify(str(entry.reason))
	# Someone came up to you (a halt, a confrontation, an attack): face them.
	if game.in_encounter() and game.gameplay_active and not game.request_busy and not game.ui.bar.showing_encounter() \
			and game.ui.modal_kind != "death":
		game.ui.close_modal_now()
		game.ui.bar.open()
	elif not game.in_encounter() and game.ui.bar.showing_encounter() and not game.request_busy and not game.ui.bar.round_playing:
		game.ui.bar.ended()
	_react_to_fight(before)
	var was_alive: bool = before.get("player", {}).get("alive", true)
	if was_alive and not game.run_state["player"].get("alive", true):
		await game.die()


## A real-time fight (D-41): it starting, blows landing or missing, people going down, it ending.
func _react_to_fight(before: Dictionary) -> void:
	var was_fighting := typeof(before.get("fight")) == TYPE_DICTIONARY
	if game.in_fight() and not was_fighting and game.gameplay_active:
		game.ui.close_modal_now()
		if game.ui.bar.visible and not game.request_busy:
			game.ui.bar.close() # Hands free: you need to move.
		for entry in game.run_state.fight.get("log", []):
			if str(entry.get("kind", "")) == "joins":
				var joiner := game.get_node_or_null("NPCs/%s/PaintedActor" % entry.who)
				if joiner:
					joiner.play_gesture("gesture")
		var names := PackedStringArray()
		for who in game.run_state.fight.get("attackers", []):
			names.append(str(game.ui.npc_record(str(who)).get("name", "Someone")))
		game.ui.notify("%s %s coming at you! Step out of reach as they wind up; Space and F strike (hold F with a shield). "
			% [" and ".join(names), "is" if names.size() == 1 else "are"]
			+ "You can still talk (T): plead, explain, call for help, or say you give up.")
	elif was_fighting and not game.in_fight() and game.run_state["player"].get("alive", true):
		var now_cell := Vector2i(int(game.run_state.player.x), int(game.run_state.player.y))
		if now_cell.distance_to(game.predicted_cell) > 3.0: # Marched off by the guards.
			game.snap_to_server()
			game.camera.reset_smoothing()
	var old_journal: Array = before.get("journal", [])
	var journal: Array = game.run_state.get("journal", [])
	for index in range(old_journal.size(), journal.size()):
		var entry: Dictionary = journal[index]
		if entry.get("kind") != "fight":
			continue
		var who := str(entry.get("npc_id", ""))
		game.ui.notify(str(entry.reason))
		if who == "player":
			continue
		var actor := game.get_node_or_null("NPCs/" + who) as Node2D
		if actor:
			actor.get_node("PaintedActor").play_gesture("gesture")
		if str(entry.get("category", "")) in ["hit", "killed"]:
			game.player_visual.hurt(1.0 if actor == null or actor.position.x <= game.player.position.x else -1.0)
			game.hurt_flash.modulate.a = 1.0
			create_tween().tween_property(game.hurt_flash, "modulate:a", 0.0, 0.8)
			game.shake_camera(12.0 if str(entry.get("category", "")) == "killed" else 9.0)
	for npc in game.run_state.get("npcs", []): # Punched to the ground (or disabled by a first strike).
		if npc.get("down", false) and npc.get("alive", true):
			var painted := game.get_node_or_null("NPCs/%s/PaintedActor" % npc.id)
			if painted and not painted.dead:
				painted.knock_down(1.0 if painted.global_position.x >= game.player.global_position.x else -1.0)


## A parchment speech bubble over someone's head; long lines are clipped (the log has them in full).
func show_bubble(npc_id: String, text: String) -> void:
	var actor := game.get_node_or_null("NPCs/" + npc_id) as Node2D
	if actor == null:
		return
	var bubble := actor.get_node_or_null("Speech") as PanelContainer
	if bubble == null:
		bubble = PanelContainer.new()
		bubble.name = "Speech"
		bubble.mouse_filter = Control.MOUSE_FILTER_IGNORE
		bubble.add_theme_stylebox_override("panel", game.UITheme.frame_box("paper", 12, 2))
		var words := Label.new()
		words.name = "Words"
		words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		words.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		words.custom_minimum_size = Vector2(200, 0)
		words.add_theme_font_override("font", game.UITheme.serif())
		words.add_theme_font_size_override("font_size", 14)
		words.add_theme_color_override("font_color", game.UITheme.INK)
		bubble.add_child(words)
		var tail := Polygon2D.new()
		tail.name = "Tail"
		tail.color = game.UITheme.PARCHMENT.darkened(0.08)
		tail.polygon = PackedVector2Array([Vector2(-8, -2), Vector2(8, -2), Vector2(-2, 12)])
		bubble.add_child(tail)
		actor.add_child(bubble)
	(bubble.get_node("Words") as Label).text = text if text.length() <= 150 else text.left(147).strip_edges() + "…"
	bubble.reset_size()
	bubble.modulate = Color.WHITE
	_place_bubble.call_deferred(bubble)
	var fade := bubble.create_tween()
	fade.tween_interval(4.5)
	fade.tween_property(bubble, "modulate:a", 0.0, 0.6)


func _place_bubble(bubble: PanelContainer) -> void:
	if not is_instance_valid(bubble):
		return
	bubble.reset_size()
	# Two people talking side by side: each bubble leans away from the other, so they don't overlap.
	var lean := 0.0
	var actor := bubble.get_parent() as Node2D
	var npc: Dictionary = game.ui.npc_record(str(actor.name)) if actor else {}
	var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
	var chatting = their_mind.get("chatting_with")
	if typeof(chatting) == TYPE_DICTIONARY:
		var partner := game.get_node_or_null("NPCs/" + str(chatting.id)) as Node2D
		if partner and absf(partner.position.x - actor.position.x) < bubble.size.x + 20.0:
			lean = (bubble.size.x * 0.5 + 6.0) * (1.0 if actor.position.x >= partner.position.x else -1.0)
	bubble.position = Vector2(-bubble.size.x * 0.5 + lean, -150.0 - bubble.size.y)
	(bubble.get_node("Tail") as Polygon2D).position = Vector2(bubble.size.x * 0.5 - lean, bubble.size.y - 2)


## Map trees are authored scene art; hide the felled ones and let the player walk through.
func _apply_world_features() -> void:
	for obj in game.run_state.get("objects", {}).values():
		if not obj.has("scene_node"):
			continue
		var standing := str(obj["condition"]) == "usable"
		var node := game.get_node_or_null(str(obj["scene_node"])) as CanvasItem
		if node:
			node.visible = standing
		var shape := game.get_node_or_null("BuildingCollision/%s/CollisionShape2D" % obj.get("geometry_name", "")) as CollisionShape2D
		if shape and not standing:
			shape.set_deferred("disabled", true)


## Felled or broken things topple and fade. A copy animates while the real node is hidden.
func start_fall(entry: Dictionary) -> void:
	var transformed = entry.get("transformed")
	if typeof(transformed) != TYPE_DICTIONARY:
		return
	var obj: Dictionary = game.run_state.get("objects", {}).get(transformed["id"], {})
	var node := game.get_node_or_null(str(obj.get("scene_node", "M2Objects/" + str(transformed["id"])))) as Node2D
	if node == null or not node.visible:
		return
	var ghost := node.duplicate() as Node2D
	for key in ["placeholder", "dynamic"]:
		if ghost.has_meta(key):
			ghost.remove_meta(key)
	node.get_parent().add_child(ghost)
	var tree := str(obj.get("feature", "")) == "tree"
	var away := 1.0 if ghost.global_position.x >= game.player.global_position.x else -1.0
	var tween := create_tween()
	tween.tween_property(ghost, "rotation", away * (1.45 if tree else 0.6), 0.95 if tree else 0.35) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	tween.tween_callback(func() -> void:
		game.effects.sound.pitch_scale = 0.4
		game.effects.sound.play())
	tween.tween_property(ghost, "modulate:a", 0.0, 0.5)
	tween.tween_callback(ghost.queue_free)


## New objects pop into place (after a fall has landed, if there was one).
func reveal_new_objects(entry: Dictionary) -> void:
	var delay := 1.0 if typeof(entry.get("transformed")) == TYPE_DICTIONARY else 0.0
	for id in entry.get("made_ids", []):
		var sprite := game.get_node_or_null("M2Objects/" + str(id)) as Sprite2D
		if sprite == null or not sprite.visible:
			continue
		var size := sprite.scale
		sprite.scale = Vector2.ZERO
		create_tween().tween_property(sprite, "scale", size, 0.3).set_delay(delay) \
			.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)


func play_harm(entry: Dictionary) -> void:
	var harm = entry.get("harm")
	if typeof(harm) != TYPE_DICTIONARY:
		return
	game.player_visual.play_gesture("gesture")
	if str(harm.get("method", "melee")) == "thrown" and harm.get("weapon_id") != null:
		var thrown := game.get_node_or_null("M2Objects/" + str(harm.weapon_id)) as Node2D
		if thrown:
			var landing := thrown.position
			thrown.position = game.player.position + Vector2(0, -30)
			var flight := create_tween()
			flight.tween_property(thrown, "position", landing, 0.35).set_trans(Tween.TRANS_QUAD)
			flight.parallel().tween_property(thrown, "rotation", thrown.rotation + TAU, 0.35)
	var actor := game.get_node_or_null("NPCs/" + str(harm["target_id"])) as Node2D
	if actor == null:
		return
	var painted := actor.get_node("PaintedActor")
	var away := 1.0 if actor.global_position.x >= game.player.global_position.x else -1.0
	match str(harm["result"]):
		"killed":
			painted.die(away)
		"wounded":
			painted.hurt(away)
