extends Node2D

const CELL := 32.0
const WORLD_SIZE := Vector2(3072, 2304)
const WALK_SPEED := 230.0 # 7.1875 cells/second, shared with the service.
const RUN_SPEED := 368.0 # 11.5 cells/second while Shift is held.
const SERVER := "http://127.0.0.1:8765"

@onready var player: CharacterBody2D = $Player
@onready var player_sprite: Sprite2D = $Player/Sprite2D
@onready var player_visual: Node2D = $Player/PaintedActor
@onready var camera: Camera2D = $Player/Camera2D
@onready var gate_shape: CollisionShape2D = $WorldCollision/ClosedGate/CollisionShape2D
@onready var gate_sprite: Sprite2D = $Map/Gate
@onready var gate_opening: ColorRect = $Map/GateOpening

var run_state: Dictionary = {}
var request_busy := false
var gameplay_active := false
var movement_sync_active := false
var move_queue: Array[Dictionary] = []
var npc_targets: Dictionary = {}
var npc_facing: Dictionary = {}
var clock_pending_ms := 0.0
var predicted_cell := Vector2i(48, 68)
var facing_row := 0
var walk_time := 0.0
var menu: PanelContainer
var message: Label
var hud: Label
var hint: Label
var trace_panel: PanelContainer
var trace_text: Label
var gate_button: Button
var victory_panel: PanelContainer
var ui: Control
var effects: Node2D
var nearby_target := ""
var nearby_ids: Array[String] = []
var footstep_distance := 0.0
var camera_zoom := 1.0
var sound_volume := 0.7
var sync_error := false


func _ready() -> void:
	$NPCPreview.hide()
	$M2Objects.hide()
	_build_ui()
	effects = preload("res://scripts/feel_effects.gd").new()
	effects.z_index = -1
	add_child(effects)
	var settings := ConfigFile.new()
	if settings.load("user://presentation.cfg") == OK:
		camera_zoom = clampf(float(settings.get_value("feel", "zoom", 1.0)), 0.75, 1.25)
		sound_volume = clampf(float(settings.get_value("feel", "volume", 0.7)), 0.0, 1.0)
	_save_settings()
	_check_health()


func _cell_center(x: int, y: int) -> Vector2:
	return Vector2((float(x) + 0.5) * CELL, (float(y) + 0.5) * CELL)


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	ui = preload("res://scripts/game_ui.gd").new()
	layer.add_child(ui)
	ui.build(self)


func _start(mode: String) -> void:
	if request_busy:
		return
	request_busy = true
	message.text = "Connecting to local simulation…"
	var reply := await _api(HTTPClient.METHOD_POST, "/runs", {"mode": mode})
	request_busy = false
	if not reply["ok"]:
		message.text = "Backend unavailable. Run tools/run_m0.ps1, then try again."
		return
	_enter_run(reply["data"])


func _check_health() -> void:
	var reply := await _api(HTTPClient.METHOD_GET, "/health")
	if menu.visible:
		message.text = "Local simulation ready. Start or resume a run." if reply["ok"] else "Start the local backend first: tools/run_m0.ps1"


func _resume() -> void:
	if request_busy:
		return
	if not FileAccess.file_exists("user://last_run.json"):
		message.text = "There is no saved run yet."
		return
	var file := FileAccess.open("user://last_run.json", FileAccess.READ)
	var saved = JSON.parse_string(file.get_as_text())
	if typeof(saved) != TYPE_DICTIONARY or not saved.has("run_id"):
		message.text = "The saved run pointer is invalid. Start a new run."
		return
	request_busy = true
	var reply := await _api(HTTPClient.METHOD_GET, "/runs/" + str(saved["run_id"]))
	request_busy = false
	if not reply["ok"]:
		message.text = "Could not resume. Check that the backend and save database are available."
		return
	_enter_run(reply["data"])


func _enter_run(state: Dictionary, save_pointer := true) -> void:
	run_state = state
	move_queue.clear()
	clock_pending_ms = 0.0
	movement_sync_active = false
	predicted_cell = Vector2i(int(state["player"]["x"]), int(state["player"]["y"]))
	if save_pointer:
		var file := FileAccess.open("user://last_run.json", FileAccess.WRITE)
		file.store_string(JSON.stringify({"run_id": run_state["run_id"]}))
	sync_error = false
	request_busy = false
	ui.modal.hide()
	ui.modal_kind = ""
	_apply_building_geometry(int(state.get("geometry_version", 1)))
	player.position = _cell_center(int(state["player"]["x"]), int(state["player"]["y"]))
	camera.reset_smoothing()
	menu.hide()
	hud.show()
	hint.show()
	_spawn_npcs()
	$M2Objects.visible = not run_state.get("objects", {}).is_empty()
	_sync_display()
	if int(state.get("geometry_version", 1)) < 2:
		ui.notify("Earlier map restored. Begin a new journey to test building and tree collisions.")
	if state["inside_city"]:
		victory_panel.show()
		gameplay_active = false
	else:
		gameplay_active = true


func _spawn_npcs() -> void:
	var old := get_node_or_null("NPCs")
	if old:
		remove_child(old)
		old.queue_free()
	var group := Node2D.new()
	group.name = "NPCs"
	group.y_sort_enabled = true
	add_child(group)
	npc_targets.clear()
	npc_facing.clear()
	for npc in run_state["npcs"]:
		var actor := Node2D.new()
		actor.name = str(npc["id"])
		actor.position = _cell_center(int(npc["x"]), int(npc["y"]))
		group.add_child(actor)
		var presence := preload("res://scripts/actor_presence.gd").new()
		actor.add_child(presence)
		var painted := preload("res://scenes/painted_actor.tscn").instantiate()
		painted.name = "PaintedActor"
		painted.actor_id = str(npc["name"]).to_lower()
		actor.add_child(painted)
		npc_targets[str(npc["id"])] = actor.position
		npc_facing[str(npc["id"])] = 0
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


func _animate_npcs(delta: float) -> void:
	for npc in run_state.get("npcs", []):
		var id := str(npc["id"])
		var actor := get_node_or_null("NPCs/" + id) as Node2D
		if actor == null:
			continue
		var target: Vector2 = npc_targets.get(id, actor.position)
		var before := actor.position
		actor.position = actor.position.move_toward(target, 86.0 * delta)
		var travel := actor.position - before
		var painted := actor.get_node("PaintedActor")
		var facing := int(npc_facing.get(id, 0))
		var mode := "idle"
		if travel.length() > 0.05:
			facing = 3 if travel.x > 0.0 else 1 if travel.x < 0.0 else 0 if travel.y > 0.0 else 2
			npc_facing[id] = facing
			mode = "walk"
		elif npc.has("controller"):
			mode = str(npc["controller"].get("activity", "idle"))
			if mode == "wait":
				mode = "idle"
		painted.set_motion(facing, mode, travel.length(), delta)


func _apply_building_geometry(version: int) -> void:
	var file_name := "world_geometry_v2.json" if version == 2 else "world_geometry.json"
	var geometry = JSON.parse_string(FileAccess.get_file_as_string("res://data/" + file_name))
	if typeof(geometry) != TYPE_DICTIONARY:
		push_error("Could not load building geometry: " + file_name)
		return
	for item in geometry["buildings"] + geometry["obstacles"]:
		var body := get_node_or_null("BuildingCollision/" + str(item["name"])) as StaticBody2D
		if body == null:
			continue
		var cells: Array = item["cells"]
		var shape_node := body.get_node("CollisionShape2D") as CollisionShape2D
		var rectangle := RectangleShape2D.new()
		rectangle.size = Vector2(float(cells[2]), float(cells[3])) * CELL
		shape_node.shape = rectangle
		shape_node.set_deferred("disabled", version < 2)
		body.position = Vector2(float(cells[0]) + float(cells[2]) * 0.5,
			float(cells[1]) + float(cells[3]) * 0.5) * CELL


func _facing_for(direction: Vector2) -> int:
	if absf(direction.x) > 0.35 and absf(direction.y) > 0.35:
		if direction.y > 0.0:
			return 4 if direction.x > 0.0 else 5
		return 7 if direction.x > 0.0 else 6
	if direction.y < -0.35:
		return 2
	if direction.y > 0.35:
		return 0
	return 3 if direction.x > 0.0 else 1


func _cardinal_fallback(view: int) -> int:
	return 0 if view == 4 or view == 5 else 2 if view == 6 or view == 7 else view


func _physics_process(delta: float) -> void:
	camera.zoom = camera.zoom.lerp(Vector2.ONE * camera_zoom, minf(1.0, delta * 10))
	_update_target()
	if not gameplay_active or request_busy or ui.modal.visible or sync_error:
		player.velocity = Vector2.ZERO
		player_sprite.frame = _cardinal_fallback(facing_row) * 3
		player_visual.set_motion(facing_row, "idle", 0.0, delta)
		return
	_animate_npcs(delta)
	if int(run_state.get("seed_version", 1)) >= 3:
		clock_pending_ms += delta * 1000.0
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	var is_running := Input.is_action_pressed("run")
	if move_queue.size() >= 16:
		direction = Vector2.ZERO
		ui.notify("Waiting for your journey to save…")
	var speed := RUN_SPEED if is_running else WALK_SPEED
	player.velocity = player.velocity.move_toward(direction * speed, (9600.0 if direction == Vector2.ZERO else 7200.0) * delta)
	var before := player.position
	player.move_and_slide()
	player.position = player.position.clamp(Vector2(10, 10), WORLD_SIZE - Vector2(10, 10))
	var travelled := player.position.distance_to(before)
	camera.offset = camera.offset.lerp(direction * 10.0, minf(1.0, delta * 14.0))
	if direction != Vector2.ZERO:
		var visual_direction := player.get_real_velocity().normalized() if travelled > 0.15 else direction
		facing_row = _facing_for(visual_direction)
	if travelled > 0.15:
		walk_time += travelled / 22.0
		var phase: int = [0, 1, 0, 2][int(walk_time) % 4]
		player_sprite.frame = _cardinal_fallback(facing_row) * 3 + phase
		footstep_distance += travelled
		if footstep_distance >= (60.0 if is_running else 48.0):
			footstep_distance = 0
			effects.step(player.position, is_running)
	else:
		walk_time = 0.0
		player_sprite.frame = _cardinal_fallback(facing_row) * 3
	player_visual.set_motion(facing_row, "run" if is_running and travelled > 0.15 else "walk" if travelled > 0.15 else "idle", travelled, delta)
	var cell := Vector2i(int(floor(player.position.x / CELL)), int(floor(player.position.y / CELL)))
	if cell != predicted_cell:
		move_queue.append({"cell": cell, "running": is_running})
		predicted_cell = cell
		if not movement_sync_active:
			_flush_moves()
	if int(run_state.get("seed_version", 1)) >= 3 and clock_pending_ms >= 500.0 and not movement_sync_active:
		_flush_moves()


func _flush_moves() -> void:
	if movement_sync_active:
		return
	movement_sync_active = true
	while gameplay_active and (not move_queue.is_empty() or
		(int(run_state.get("seed_version", 1)) >= 3 and clock_pending_ms >= 500.0)):
		var sending_move := not move_queue.is_empty()
		var elapsed_ms := 0
		var body: Dictionary
		var path := "/move"
		if sending_move:
			var step: Dictionary = move_queue.pop_front()
			var cell: Vector2i = step["cell"]
			body = {"x": cell.x, "y": cell.y,
				"expected_version": run_state["event_seq"],
				"running": bool(step["running"]), "request_id": _request_id("move")}
		else:
			elapsed_ms = mini(floori(clock_pending_ms), 1000)
			clock_pending_ms -= float(elapsed_ms)
			path = "/explore"
			body = {"elapsed_ms": elapsed_ms, "expected_version": run_state["event_seq"],
				"request_id": _request_id("explore")}
		var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state["run_id"]) + path, body)
		# Retrying the identical request is safe even when the first response was lost.
		if not reply["ok"] and (int(reply.status) == 0 or int(reply.status) >= 500):
			reply = await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state["run_id"]) + path, body)
		if reply["ok"]:
			run_state = reply["data"]["state"]
			_sync_display()
			if run_state["inside_city"]:
				gameplay_active = false
				victory_panel.show()
				move_queue.clear()
		else:
			if not sending_move:
				clock_pending_ms += float(elapsed_ms)
			sync_error = true
			move_queue.clear()
			var fresh := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id))
			if fresh.ok:
				run_state = fresh.data
				sync_error = false
				_sync_display()
			move_queue.clear()
			predicted_cell = Vector2i(int(run_state["player"]["x"]), int(run_state["player"]["y"]))
			player.position = _cell_center(predicted_cell.x, predicted_cell.y)
			ui.notify("Connection lost. Pause and resume your journey to reconnect." if sync_error else
				"That path is blocked." if sending_move else "The village clock is reconnecting.")
			break
	movement_sync_active = false


func _toggle_gate() -> void:
	if run_state.get("mode", "normal") != "developer" or request_busy or movement_sync_active or not move_queue.is_empty():
		return
	request_busy = true
	var body := {
		"open": not run_state["gate_open"], "expected_version": run_state["event_seq"],
		"request_id": str(run_state["run_id"]) + ":gate:" + str(run_state["event_seq"] + 1)
	}
	var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state["run_id"]) + "/dev/gate", body)
	if reply["ok"]:
		run_state = reply["data"]["state"]
		_sync_display()
	request_busy = false


func _sync_display() -> void:
	gate_shape.set_deferred("disabled", bool(run_state["gate_open"]))
	gate_sprite.visible = not bool(run_state["gate_open"])
	gate_opening.visible = bool(run_state["gate_open"])
	var carried: Array[String] = []
	for obj in run_state.get("objects", {}).values():
		if obj["holder_id"] == "player":
			carried.append(str(obj["name"]))
	hud.text = "The gate lies to the north ↑" if not run_state["gate_open"] else "The city gate is open ↑"
	ui.bag_button.text = "Bag %s  [I]" % carried.size()
	for object_id in run_state.get("objects", {}):
		var sprite := get_node_or_null("M2Objects/" + str(object_id)) as Sprite2D
		if sprite:
			var obj: Dictionary = run_state["objects"][object_id]
			sprite.visible = obj["holder_id"] == null
			sprite.position = _cell_center(int(obj["x"]), int(obj["y"]))
	for npc in run_state.get("npcs", []):
		npc_targets[str(npc["id"])] = _cell_center(int(npc["x"]), int(npc["y"]))
	gate_button.text = "CLOSE GATE (TEST)" if run_state["gate_open"] else "OPEN GATE (TEST)"
	trace_text.text = "RUN " + str(run_state["run_id"]).substr(0, 12) + "\n" \
		+ "Mode: " + str(run_state["mode"]) + "\n" \
		+ "Event: " + str(int(run_state["event_seq"])) + "\n" \
		+ "Tick: " + str(int(run_state["tick"])) + " (" + str(int(run_state["sim_time_ms"])) + " ms)\n" \
		+ "Player: (" + str(int(run_state["player"]["x"])) + ", " + str(int(run_state["player"]["y"])) + ")\n" \
		+ "Gate: " + ("open" if run_state["gate_open"] else "closed") + "\n" \
		+ "Objective: " + ("complete" if run_state["inside_city"] else "active")
	trace_panel.visible = run_state["mode"] == "developer" and trace_panel.visible


func _refresh_trace() -> void:
	if run_state.is_empty() or movement_sync_active:
		return
	var reply := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state["run_id"]))
	if reply["ok"]:
		run_state = reply["data"]
		_sync_display()


func _api(method: HTTPClient.Method, path: String, body: Dictionary = {}) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)
	request.timeout = 5.0
	var payload := JSON.stringify(body) if method != HTTPClient.METHOD_GET else ""
	var err := request.request(SERVER + path, ["Content-Type: application/json"], method, payload)
	if err != OK:
		request.queue_free()
		return {"ok": false, "status": 0}
	var completed: Array = await request.request_completed
	request.queue_free()
	var status := int(completed[1])
	var data = JSON.parse_string((completed[3] as PackedByteArray).get_string_from_utf8())
	return {"ok": status >= 200 and status < 300 and typeof(data) == TYPE_DICTIONARY,
		"status": status, "data": data}


func _request_id(kind: String) -> String:
	return str(run_state.run_id) + ":" + kind + ":" + Crypto.new().generate_random_bytes(8).hex_encode()


func _save_settings() -> void:
	var settings := ConfigFile.new()
	settings.set_value("feel", "zoom", camera_zoom)
	settings.set_value("feel", "volume", sound_volume)
	settings.save("user://presentation.cfg")
	AudioServer.set_bus_volume_db(0, linear_to_db(maxf(0.001, sound_volume)))
	AudioServer.set_bus_mute(0, sound_volume == 0.0)


func _update_target() -> void:
	if run_state.is_empty():
		return
	var candidates: Array[Dictionary] = []
	for id in run_state.get("objects", {}):
		var obj: Dictionary = run_state.objects[id]
		if obj.holder_id != null:
			continue
		var distance := player.position.distance_to(_cell_center(int(obj.x), int(obj.y)))
		if distance <= 76:
			candidates.append({"id": str(id), "distance": distance})
	for npc in run_state.npcs:
		var npc_actor := get_node_or_null("NPCs/" + str(npc.id)) as Node2D
		var npc_position := npc_actor.position if npc_actor else _cell_center(int(npc.x), int(npc.y))
		var distance := player.position.distance_to(npc_position)
		if distance <= 80:
			candidates.append({"id": str(npc.id), "distance": distance})
		var plate := get_node_or_null("NPCs/" + str(npc.id) + "/Nameplate") as Label
		if plate:
			plate.modulate.a = clampf((240 - distance) / 90, 0, 1)
	candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return a.distance < b.distance)
	nearby_ids.clear()
	for candidate in candidates:
		nearby_ids.append(candidate.id)
	if nearby_target not in nearby_ids:
		nearby_target = nearby_ids[0] if not nearby_ids.is_empty() else ""
	effects.has_target = not nearby_target.is_empty() and not ui.modal.visible
	ui.prompt.text = ""
	if not nearby_target.is_empty():
		var target: Dictionary = run_state.get("objects", {}).get(nearby_target, {})
		var verb := "Pick up"
		if target.is_empty():
			for npc in run_state.npcs:
				if npc.id == nearby_target:
					target = npc
			verb = "Meet"
		elif target.owner_id != null:
			verb = "Inspect"
		var target_actor := get_node_or_null("NPCs/" + nearby_target) as Node2D
		effects.marker = target_actor.position if target_actor else _cell_center(int(target.x), int(target.y))
		ui.prompt.text = "E  %s %s   ·   F  Inspect" % [verb, str(target.name)]
		if nearby_ids.size() > 1:
			ui.prompt.text += "   ·   Tab  Next"
	ui.area.text = "THE CITY GATE" if player.position.y < 600 else "THE CRAFTSMEN'S ROW" if player.position.y < 1200 else "THE WAYSIDE INN" if player.position.y < 1800 else "THE SOUTH ROAD"


func _interact() -> void:
	if nearby_target.is_empty() or request_busy:
		return
	var obj: Dictionary = run_state.get("objects", {}).get(nearby_target, {})
	if not obj.is_empty() and obj.owner_id == null:
		_quick_action("take", nearby_target)
	else:
		ui.inspect(nearby_target)


func _quick_action(verb: String, id: String) -> void:
	if request_busy or not gameplay_active or sync_error:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	if sync_error:
		request_busy = false
		return
	var body := {"text": verb + " " + id.replace("_", " "), "selected_ids": [id],
		"expected_version": run_state.event_seq, "request_id": _request_id(verb)}
	var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/actions", body)
	if not reply.ok and (int(reply.status) == 0 or int(reply.status) >= 500):
		reply = await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/actions", body)
	request_busy = false
	if reply.ok:
		run_state = reply.data.state
		_sync_display()
		ui.notify(str(run_state.last_action.reason))
		if run_state.last_action.category == "success":
			effects.pickup_sound.play()
			player_visual.play_gesture("pickup" if verb == "take" else "gesture")
		if ui.modal_kind == "bag":
			ui.open_bag()
		elif ui.modal_kind == "inspect":
			ui.close_modal()
	else:
		# Reconcile a lost response before allowing another world-changing action.
		request_busy = true
		var fresh := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id))
		if fresh.ok:
			run_state = fresh.data
			_sync_display()
		else:
			sync_error = true
		request_busy = false
		ui.notify("Could not confirm the action. Your saved journey is preserved.")


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and gameplay_active and not ui.modal.visible:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP or event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			camera_zoom = clampf(camera_zoom + (0.05 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -0.05), 0.75, 1.25)
			_save_settings()
	if not event is InputEventKey or not event.pressed or event.echo or run_state.is_empty():
		return
	if event.keycode == KEY_ESCAPE:
		if ui.modal.visible:
			ui.close_modal()
		else:
			ui.open_pause()
	elif event.keycode == KEY_F3 and run_state.mode == "developer":
		trace_panel.visible = not trace_panel.visible
	elif (event.keycode == KEY_I and ui.modal_kind == "bag") or (event.keycode == KEY_J and ui.modal_kind == "journal"):
		ui.close_modal()
	elif not ui.modal.visible and gameplay_active:
		match event.keycode:
			KEY_E: _interact()
			KEY_F:
				if not nearby_target.is_empty():
					ui.inspect(nearby_target)
			KEY_I: ui.open_bag()
			KEY_J: ui.open_journal()
			KEY_TAB:
				if nearby_ids.size() > 1:
					nearby_target = nearby_ids[(nearby_ids.find(nearby_target) + 1) % nearby_ids.size()]
	get_viewport().set_input_as_handled()


func _back_to_menu() -> void:
	if request_busy:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	gameplay_active = false
	if not run_state.is_empty():
		await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/checkpoint")
	request_busy = false
	run_state = {}
	menu.show()
	ui.modal.hide()
	ui.modal_kind = ""
	ui.prompt.text = ""
	effects.has_target = false
	trace_panel.hide()
	victory_panel.hide()
	message.text = "Your journey is saved."
