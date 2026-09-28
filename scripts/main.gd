extends Node2D

const UITheme := preload("res://scripts/ui/ui_theme.gd")

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
var trace_panel: PanelContainer
var trace_text: Label
var gate_button: Button
var victory_panel: PanelContainer
var victory_route: Label
var ui: Control
var effects: Node2D
var nearby_target := "" # The nearest thing, for E.
var warm_until: Dictionary = {} # npc id -> seconds: show a warm mark over their head until then.
var footstep_distance := 0.0
var camera_zoom := 1.0
var sound_volume := 0.7
var sync_error := false
var ai_status: Dictionary = {}
var last_trace = null # Developer runs receive the judge trace with each attempt.

# Objects without authored art show a loading ring until their painting arrives (loading_ring.gd).
const OBJECT_HEIGHT := 46.0
const OBJECT_MAX_WIDTH := 60.0
const REACH_CELLS := 2.5 # Matches backend m2.REACH_CELLS.
const NEARBY_CELLS := 8.0 # Try Something can involve anything this close; the player walks there first.
var scripted_walk := false
var shown_speech: Dictionary = {} # npc id -> key of the last line shown in a bubble
var shown_cues: Dictionary = {} # npc id -> key of the last regard cue shown
var thinking_active := false
## Cheap counters read by tools/profile_frame.gd: key -> [count, total microseconds, total bytes].
var prof: Dictionary = {}


var prof_max: Dictionary = {} # key -> largest single value seen (e.g. ms between world updates)
var last_state_usec := 0


func _prof_max(key: String, value: float) -> void:
	prof_max[key] = maxf(float(prof_max.get(key, 0.0)), value)


func _prof(key: String, started_usec: int, size := 0) -> void:
	var entry: Array = prof.get(key, [0, 0, 0])
	var spent := Time.get_ticks_usec() - started_usec
	prof[key] = [entry[0] + 1, entry[1] + spent, entry[2] + size]
	_prof_max("slowest " + key + " ms", spent / 1000.0)
var object_textures: Dictionary = {} # object id -> resolved Texture2D
var sprite_state: Dictionary = {} # asset id -> "polling" | "failed"


func _ready() -> void:
	$NPCPreview.hide()
	$M2Objects.hide()
	_build_ui()
	_extend_ground()
	effects = preload("res://scripts/feel_effects.gd").new()
	effects.z_index = -1
	add_child(effects)
	var settings := ConfigFile.new()
	if settings.load("user://presentation.cfg") == OK:
		camera_zoom = clampf(float(settings.get_value("feel", "zoom", 1.0)), 0.75, 1.25)
		sound_volume = clampf(float(settings.get_value("feel", "volume", 0.7)), 0.0, 1.0)
	_save_settings()
	_check_health()


## The ground carries on a little past the south edge of the map, fading into shadow, so the view can
## shift down to keep the stranger clear of the bottom panels without showing an empty void.
func _extend_ground() -> void:
	var ground := $Map/Ground as Sprite2D
	var size := ground.texture.get_size()
	var depth := 520.0
	var beyond := Sprite2D.new()
	beyond.name = "GroundBeyond"
	beyond.texture = ground.texture
	beyond.centered = false
	beyond.region_enabled = true
	beyond.region_rect = Rect2(0, size.y - depth, size.x, depth)
	beyond.flip_v = true # Mirrored, so it meets the map edge without a seam.
	beyond.position = Vector2(0, size.y)
	beyond.z_index = ground.z_index
	beyond.material = ground.material
	beyond.texture_filter = ground.texture_filter
	$Map.add_child(beyond)
	var shade := Polygon2D.new()
	shade.name = "EdgeShade"
	shade.z_index = -18
	shade.polygon = PackedVector2Array([Vector2(0, size.y - 40), Vector2(size.x, size.y - 40),
		Vector2(size.x, size.y + depth), Vector2(0, size.y + depth)])
	var dusk := Color(0.05, 0.06, 0.04, 0.0)
	shade.vertex_colors = PackedColorArray([dusk, dusk, Color(dusk, 0.85), Color(dusk, 0.85)])
	$Map.add_child(shade)


## How far the view shifts down so the stranger stays clear of the bottom panels: the dialogue bar,
## or the pack near the south edge, where the camera can't follow any further (offset goes past limits).
func _camera_lift() -> float:
	var screen := get_viewport_rect().size
	var zoom := camera.zoom.y
	var covered: float = ui.bottom_cover()
	var half := screen.y * 0.5 / zoom
	var centre := clampf(player.position.y, float(camera.limit_top) + half, float(camera.limit_bottom) - half)
	var feet := screen.y * 0.5 + (player.position.y - centre) * zoom
	var lift := maxf(0.0, (feet + 28.0 * zoom - (screen.y - covered)) / zoom)
	if ui.bar.visible:
		lift = maxf(lift, covered * 0.5 / zoom) # Centred in what's left of the view.
	return lift


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
	if reply["ok"] and typeof(reply["data"].get("ai")) == TYPE_DICTIONARY:
		ai_status = reply["data"]["ai"]
	if menu.visible:
		message.text = ("Local simulation ready. Start or resume a run." + (
			"" if ai_ready() else "\nAI crafting is off: add OPENAI_API_KEY to backend/.env and restart the backend.")
			) if reply["ok"] else "Start the local backend first: tools/run_m0.ps1"


func ai_ready() -> bool:
	return bool(ai_status.get("judge", false))


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
	last_trace = null
	for child in $M2Objects.get_children():
		if child.has_meta("dynamic"):
			$M2Objects.remove_child(child)
			child.queue_free()
	for tree in $Foliage.get_children(): # A previous journey may have felled some.
		if tree.name.begins_with("Tree"):
			tree.visible = true
			tree.rotation = 0.0
			tree.modulate = Color.WHITE
	player.position = _cell_center(int(state["player"]["x"]), int(state["player"]["y"]))
	player_visual.revive()
	camera.reset_smoothing()
	menu.hide()
	_spawn_npcs()
	$M2Objects.visible = not run_state.get("objects", {}).is_empty()
	_sync_display()
	ui.enter_run(state)
	if int(state.get("geometry_version", 1)) < 2:
		ui.notify("Earlier map restored. Begin a new journey to test building and tree collisions.")
	if state["inside_city"]:
		_show_victory()
		gameplay_active = false
	elif not state["player"].get("alive", true):
		gameplay_active = false
		player_visual.lie_dead()
		ui.show_death(_death_reason())
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
		if not npc.get("alive", true):
			painted.lie_dead()
		npc_targets[str(npc["id"])] = actor.position
		npc_facing[str(npc["id"])] = 0
		var said = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("said")
		shown_speech[str(npc["id"])] = str(said.key) if typeof(said) == TYPE_DICTIONARY else ""
		var cue = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("cue")
		shown_cues[str(npc["id"])] = str(cue.key) if typeof(cue) == TYPE_DICTIONARY else ""
		var status := preload("res://scripts/ui/head_status.gd").new()
		status.name = "Status"
		status.game = self
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


func _animate_npcs(delta: float) -> void:
	for npc in run_state.get("npcs", []):
		var id := str(npc["id"])
		var actor := get_node_or_null("NPCs/" + id) as Node2D
		if actor == null or not npc.get("alive", true):
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
			if typeof(chatting) == TYPE_DICTIONARY and float(chatting.get("until", 0)) > float(run_state.get("sim_time_ms", 0)):
				var partner := get_node_or_null("NPCs/" + str(chatting.id)) as Node2D
				if partner: # Two people talking turn to face each other.
					var across := partner.position - actor.position
					facing = (3 if across.x > 0.0 else 1) if absf(across.x) > absf(across.y) else (0 if across.y > 0.0 else 2)
					npc_facing[id] = facing
					mode = "idle"
			if typeof(mind) == TYPE_DICTIONARY and mind.get("facing_player", false):
				# Wary people turn to face the stranger (decided by code on the server, not by Jev).
				var toward := player.position - actor.position
				facing = (3 if toward.x > 0.0 else 1) if absf(toward.x) > absf(toward.y) else (0 if toward.y > 0.0 else 2)
				npc_facing[id] = facing
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
	# The view shifts so you stay in sight above the dialogue bar or the pack.
	var lift := _camera_lift()
	camera.offset.y = lerpf(camera.offset.y, lift, minf(1.0, delta * 6.0))
	var started := Time.get_ticks_usec()
	_update_nearby()
	_prof("update_target", started)
	if in_encounter() and gameplay_active and not thinking_active and _minds_pending():
		_flush_minds() # Everyone's next move is decided while the player chooses theirs.
	if in_encounter() and gameplay_active and not request_busy and not ui.bar.showing_encounter() \
			and ui.modal_kind != "death":
		ui.close_modal_now()
		ui.bar.open()
	if not gameplay_active or request_busy or ui.blocks_movement() or sync_error:
		if scripted_walk: # _walk_along is moving the player.
			return
		player.velocity = Vector2.ZERO
		player_sprite.frame = _cardinal_fallback(facing_row) * 3
		player_visual.set_motion(facing_row, "idle", 0.0, delta)
		return
	started = Time.get_ticks_usec()
	_animate_npcs(delta)
	_prof("animate_npcs", started)
	if int(run_state.get("seed_version", 1)) >= 3 and not in_encounter():
		clock_pending_ms += delta * 1000.0 # Face to face, rounds move time instead.
	var direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
	var is_running := Input.is_action_pressed("run")
	if move_queue.size() >= 16:
		_prof("movement_stalled_frames", Time.get_ticks_usec())
		direction = Vector2.ZERO
		ui.notify("Waiting for your journey to save…")
	var speed := RUN_SPEED if is_running else WALK_SPEED
	player.velocity = player.velocity.move_toward(direction * speed, (9600.0 if direction == Vector2.ZERO else 7200.0) * delta)
	var before := player.position
	player.move_and_slide()
	player.position = player.position.clamp(Vector2(10, 10), WORLD_SIZE - Vector2(10, 10))
	var travelled := player.position.distance_to(before)
	camera.offset = camera.offset.lerp(direction * 10.0 + Vector2(0, lift), minf(1.0, delta * 14.0))
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
		ui.note_cell(cell)
		if not movement_sync_active:
			_flush_moves()
	if not movement_sync_active and int(run_state.get("seed_version", 1)) >= 3 and clock_pending_ms >= 500.0:
		_flush_moves()
	if not thinking_active and _minds_pending():
		_flush_minds()


## Movement lane: the player's steps (batched) and the clock, one request at a time.
## People's thinking runs separately in _flush_minds, so Jev never holds up walking or time.
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
			# Every step queued since the last request goes in one batch.
			var cells := []
			var running := false
			while not move_queue.is_empty() and cells.size() < 24:
				var step: Dictionary = move_queue.pop_front()
				cells.append([step["cell"].x, step["cell"].y])
				running = running or bool(step["running"])
			body = {"cells": cells, "expected_version": run_state["event_seq"], "running": running,
				"request_id": _request_id("move")}
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
			_accept_state(reply["data"]["state"])
			if run_state["inside_city"]:
				gameplay_active = false
				_show_victory()
				move_queue.clear()
		else:
			if not sending_move:
				clock_pending_ms += float(elapsed_ms)
			move_queue.clear()
			var blocked_state = reply.data.get("state") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
			if typeof(blocked_state) == TYPE_DICTIONARY:
				_accept_state(blocked_state) # The legal steps before the blocked one were kept.
			else:
				sync_error = true
				var fresh := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id))
				if fresh.ok:
					_accept_state(fresh.data)
					sync_error = false
			predicted_cell = Vector2i(int(run_state["player"]["x"]), int(run_state["player"]["y"]))
			player.position = _cell_center(predicted_cell.x, predicted_cell.y)
			ui.notify("Connection lost. Pause and resume your journey to reconnect." if sync_error else
				"That path is blocked." if sending_move else "The village clock is reconnecting.")
			break
	movement_sync_active = false


## Thinking lane: people with something on their mind decide (Jev), alongside the movement lane.
func _flush_minds() -> void:
	if thinking_active:
		return
	thinking_active = true
	while _minds_pending():
		var body := {"expected_version": run_state["event_seq"], "request_id": _request_id("think")}
		var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state["run_id"]) + "/think", body, 40.0)
		if not reply["ok"] and (int(reply.status) == 0 or int(reply.status) >= 500):
			reply = await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state["run_id"]) + "/think", body, 40.0)
		if not reply["ok"]:
			await get_tree().create_timer(1.0).timeout # e.g. another think still finishing; try again shortly.
			continue
		_accept_state(reply["data"]["state"])
	thinking_active = false


## Replies from the two lanes can arrive in either order; the newest world state wins
## (the server applies events one at a time, so a later event already includes the earlier ones).
func _accept_state(new_state: Dictionary) -> void:
	if int(new_state.get("event_seq", 0)) < int(run_state.get("event_seq", 0)):
		return
	if run_state.has("run_id") and new_state.get("run_id") != run_state.get("run_id"):
		return # A late reply from a journey that has since been left (e.g. its thinking lane).
	if last_state_usec > 0:
		_prof_max("longest_gap_between_updates_ms", (Time.get_ticks_usec() - last_state_usec) / 1000.0)
	last_state_usec = Time.get_ticks_usec()
	var before := run_state
	run_state = new_state
	_sync_display()
	_react_to(before)


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
	var started := Time.get_ticks_usec()
	_sync_display_now()
	_prof("sync_display", started)


func _sync_display_now() -> void:
	gate_shape.set_deferred("disabled", bool(run_state["gate_open"]))
	gate_sprite.visible = not bool(run_state["gate_open"])
	gate_opening.visible = bool(run_state["gate_open"])
	for object_id in run_state.get("objects", {}):
		var obj: Dictionary = run_state["objects"][object_id]
		if obj.has("scene_node"): # Map trees keep their authored art; see _apply_world_features.
			continue
		var sprite := get_node_or_null("M2Objects/" + str(object_id)) as Sprite2D
		if sprite == null:
			if obj["holder_id"] != null:
				continue
			sprite = Sprite2D.new()
			sprite.name = str(object_id)
			sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			sprite.set_meta("dynamic", true)
			$M2Objects.add_child(sprite)
		if sprite.has_meta("dynamic"):
			_apply_object_texture(sprite, obj)
		sprite.visible = obj["holder_id"] == null
		sprite.position = _cell_center(int(obj["x"]), int(obj["y"]))
		if obj.get("installed_in") != null:
			sprite.position.y -= 36.0 # Up in its fixture, not on the ground.
	_apply_world_features()
	for npc in run_state.get("npcs", []):
		npc_targets[str(npc["id"])] = _cell_center(int(npc["x"]), int(npc["y"]))
		var said = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("said")
		if typeof(said) == TYPE_DICTIONARY and shown_speech.get(str(npc["id"]), "") != str(said.key):
			shown_speech[str(npc["id"])] = str(said.key)
			var after := float(said.get("after_ms", 0)) / 1000.0 # The second speaker in a chat answers a beat later.
			if after > 0.0:
				get_tree().create_timer(after).timeout.connect(_show_bubble.bind(str(npc["id"]), str(said.text)))
			else:
				_show_bubble(str(npc["id"]), str(said.text))
		var cue = (npc.get("mind", {}) if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}).get("cue")
		if typeof(cue) == TYPE_DICTIONARY and shown_cues.get(str(npc["id"]), "") != str(cue.key):
			shown_cues[str(npc["id"])] = str(cue.key)
			if str(cue.get("kind", "")) in ["warmer", "trusting", "easier"]:
				warm_until[str(npc["id"])] = Time.get_ticks_msec() / 1000.0 + 3.5
			if not in_encounter(): # Face to face, the round log shows it.
				ui.notify(str(cue.text))
		var plate := get_node_or_null("NPCs/%s/Nameplate" % npc["id"]) as Label
		if plate:
			plate.text = str(npc["name"]) + ("" if npc.get("alive", true) else " (dead)")
			plate.position.y = -115.0 if npc.get("alive", true) else -58.0 # Down beside a body.
	gate_button.text = "Close gate (test)" if run_state["gate_open"] else "Open gate (test)"
	trace_text.text = "RUN " + str(run_state["run_id"]).substr(0, 12) + "\n" \
		+ "Mode: " + str(run_state["mode"]) + "\n" \
		+ "Event: " + str(int(run_state["event_seq"])) + "\n" \
		+ "Tick: " + str(int(run_state["tick"])) + " (" + str(int(run_state["sim_time_ms"])) + " ms)\n" \
		+ "Player: (" + str(int(run_state["player"]["x"])) + ", " + str(int(run_state["player"]["y"])) + ")\n" \
		+ "Gate: " + ("open" if run_state["gate_open"] else "closed") + "\n" \
		+ "Objective: " + ("complete" if run_state["inside_city"] else "active")
	trace_panel.visible = run_state["mode"] == "developer" and trace_panel.visible
	ui.note_cell(Vector2i(int(run_state["player"]["x"]), int(run_state["player"]["y"])))
	ui.refresh()


func _minds_pending() -> bool:
	return gameplay_active and not run_state.is_empty() and not run_state.get("pending_minds", []).is_empty()


## Play what happened between two states: people striking the player, the player dying.
func _react_to(before: Dictionary) -> void:
	var old_journal: Array = before.get("journal", [])
	var journal: Array = run_state.get("journal", [])
	for index in range(old_journal.size(), journal.size()):
		var entry: Dictionary = journal[index]
		if entry.get("kind") == "npc":
			var speaker := get_node_or_null("NPCs/%s/PaintedActor" % entry.npc_id)
			if speaker:
				speaker.play_gesture("gesture") # A gesture as they speak.
		if entry.get("kind") == "npc_attack":
			var striker := get_node_or_null("NPCs/%s/PaintedActor" % entry.npc_id)
			if striker:
				striker.play_gesture("gesture")
			if entry.result != "missed" and run_state["player"].get("alive", true):
				player_visual.hurt(1.0)
			ui.notify(str(entry.reason))
	# Someone came up to you (a halt, a confrontation, an attack): face them.
	if in_encounter() and gameplay_active and not request_busy and not ui.bar.showing_encounter() \
			and ui.modal_kind != "death":
		ui.close_modal_now()
		ui.bar.open()
	elif not in_encounter() and ui.bar.showing_encounter() and not request_busy and not ui.bar.round_playing:
		ui.bar.ended()
	var was_alive: bool = before.get("player", {}).get("alive", true)
	if was_alive and not run_state["player"].get("alive", true):
		gameplay_active = false
		move_queue.clear()
		player_visual.die(1.0)
		await get_tree().create_timer(1.6).timeout
		ui.show_death(_death_reason())


func _show_victory() -> void:
	var admitted = run_state.get("admitted")
	var lines := PackedStringArray()
	if typeof(admitted) == TYPE_DICTIONARY:
		lines.append("Captain Roderic let you through the gate.")
		var because: Array = admitted.get("because", [])
		if not because.is_empty():
			lines.append("What weighed with him:")
			for reason in because:
				lines.append("• " + str(reason))
	else:
		lines.append("You found your own way in.")
	victory_route.text = "\n".join(lines)
	victory_panel.show()


func _death_reason() -> String:
	var journal: Array = run_state.get("journal", [])
	for index in range(journal.size() - 1, -1, -1):
		if journal[index].get("kind") == "npc_attack" and journal[index].get("result") == "killed":
			return str(journal[index].reason)
	return "You died."


func rewind() -> void:
	if request_busy:
		return
	request_busy = true
	var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/rewind", {}, 30.0)
	request_busy = false
	if reply.ok and typeof(reply.data) == TYPE_DICTIONARY:
		_enter_run(reply.data)
		ui.notify("You are back, just before the trouble began.")
	else:
		ui.notify("Could not rewind the journey (HTTP %s)." % reply.status)


## A parchment speech bubble over someone's head; long lines are clipped (the log has them in full).
func _show_bubble(npc_id: String, text: String) -> void:
	var actor := get_node_or_null("NPCs/" + npc_id) as Node2D
	if actor == null:
		return
	var bubble := actor.get_node_or_null("Speech") as PanelContainer
	if bubble == null:
		bubble = PanelContainer.new()
		bubble.name = "Speech"
		bubble.mouse_filter = Control.MOUSE_FILTER_IGNORE
		bubble.add_theme_stylebox_override("panel", UITheme.frame_box("paper", 12, 2))
		var words := Label.new()
		words.name = "Words"
		words.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		words.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		words.custom_minimum_size = Vector2(200, 0)
		words.add_theme_font_override("font", UITheme.serif())
		words.add_theme_font_size_override("font_size", 14)
		words.add_theme_color_override("font_color", UITheme.INK)
		bubble.add_child(words)
		var tail := Polygon2D.new()
		tail.name = "Tail"
		tail.color = UITheme.PARCHMENT.darkened(0.08)
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
	bubble.position = Vector2(-bubble.size.x * 0.5, -150.0 - bubble.size.y)
	(bubble.get_node("Tail") as Polygon2D).position = Vector2(bubble.size.x * 0.5, bubble.size.y - 2)

## Map trees are authored scene art; hide the felled ones and let the player walk through.
func _apply_world_features() -> void:
	for obj in run_state.get("objects", {}).values():
		if not obj.has("scene_node"):
			continue
		var standing := str(obj["condition"]) == "usable"
		var node := get_node_or_null(str(obj["scene_node"])) as CanvasItem
		if node:
			node.visible = standing
		var shape := get_node_or_null("BuildingCollision/%s/CollisionShape2D" % obj.get("geometry_name", "")) as CollisionShape2D
		if shape and not standing:
			shape.set_deferred("disabled", true)


## Felled or broken things topple and fade. A copy animates while the real node is hidden.
func _start_fall(entry: Dictionary) -> void:
	var transformed = entry.get("transformed")
	if typeof(transformed) != TYPE_DICTIONARY:
		return
	var obj: Dictionary = run_state.get("objects", {}).get(transformed["id"], {})
	var node := get_node_or_null(str(obj.get("scene_node", "M2Objects/" + str(transformed["id"])))) as Node2D
	if node == null or not node.visible:
		return
	var ghost := node.duplicate() as Node2D
	for key in ["placeholder", "dynamic"]:
		if ghost.has_meta(key):
			ghost.remove_meta(key)
	node.get_parent().add_child(ghost)
	var tree := str(obj.get("feature", "")) == "tree"
	var away := 1.0 if ghost.global_position.x >= player.global_position.x else -1.0
	var tween := create_tween()
	tween.tween_property(ghost, "rotation", away * (1.45 if tree else 0.6), 0.95 if tree else 0.35) \
		.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	tween.tween_callback(func() -> void:
		effects.sound.pitch_scale = 0.4
		effects.sound.play())
	tween.tween_property(ghost, "modulate:a", 0.0, 0.5)
	tween.tween_callback(ghost.queue_free)


## New objects pop into place (after a fall has landed, if there was one).
func _reveal_new_objects(entry: Dictionary) -> void:
	var delay := 1.0 if typeof(entry.get("transformed")) == TYPE_DICTIONARY else 0.0
	for id in entry.get("made_ids", []):
		var sprite := get_node_or_null("M2Objects/" + str(id)) as Sprite2D
		if sprite == null or not sprite.visible:
			continue
		var size := sprite.scale
		sprite.scale = Vector2.ZERO
		create_tween().tween_property(sprite, "scale", size, 0.3).set_delay(delay) \
			.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)


## Walk the player along the cells the server planned, with the normal walk animation.
func _walk_along(path: Array) -> void:
	if path.is_empty():
		return
	scripted_walk = true
	for cell in path:
		var goal := _cell_center(int(cell[0]), int(cell[1]))
		while player.position.distance_to(goal) > 0.5:
			var delta := get_process_delta_time()
			var before := player.position
			player.position = player.position.move_toward(goal, WALK_SPEED * delta)
			var step := player.position - before
			if step.length() > 0.01:
				facing_row = _facing_for(step.normalized())
			player_visual.set_motion(facing_row, "walk", step.length(), delta)
			await get_tree().process_frame
	player_visual.set_motion(facing_row, "idle", 0.0, 0.0)
	predicted_cell = Vector2i(int(path[-1][0]), int(path[-1][1]))
	scripted_walk = false


func _play_harm(entry: Dictionary) -> void:
	var harm = entry.get("harm")
	if typeof(harm) != TYPE_DICTIONARY:
		return
	player_visual.play_gesture("gesture")
	if str(harm.get("method", "melee")) == "thrown" and harm.get("weapon_id") != null:
		var thrown := get_node_or_null("M2Objects/" + str(harm.weapon_id)) as Node2D
		if thrown:
			var landing := thrown.position
			thrown.position = player.position + Vector2(0, -30)
			var flight := create_tween()
			flight.tween_property(thrown, "position", landing, 0.35).set_trans(Tween.TRANS_QUAD)
			flight.parallel().tween_property(thrown, "rotation", thrown.rotation + TAU, 0.35)
	var actor := get_node_or_null("NPCs/" + str(harm["target_id"])) as Node2D
	if actor == null:
		return
	var painted := actor.get_node("PaintedActor")
	var away := 1.0 if actor.global_position.x >= player.global_position.x else -1.0
	match str(harm["result"]):
		"killed":
			painted.die(away)
		"wounded":
			painted.hurt(away)


func _refresh_trace() -> void:
	if run_state.is_empty() or movement_sync_active:
		return
	var reply := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state["run_id"]))
	if reply["ok"]:
		run_state = reply["data"]
		_sync_display()


func _api(method: HTTPClient.Method, path: String, body: Dictionary = {}, timeout := 5.0) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)
	request.timeout = timeout
	var payload := JSON.stringify(body) if method != HTTPClient.METHOD_GET else ""
	var err := request.request(SERVER + path, ["Content-Type: application/json"], method, payload)
	if err != OK:
		request.queue_free()
		return {"ok": false, "status": 0}
	var completed: Array = await request.request_completed
	request.queue_free()
	var status := int(completed[1])
	var parse_started := Time.get_ticks_usec()
	var text := (completed[3] as PackedByteArray).get_string_from_utf8()
	# Only JSON is parsed: an error page ("Internal Server Error") is a failed reply, not something to parse.
	var data = JSON.parse_string(text) if text.strip_edges().left(1) in ["{", "["] else null
	_prof("parse " + path.get_slice("?", 0).get_file(), parse_started, (completed[3] as PackedByteArray).size())
	return {"ok": status >= 200 and status < 300 and typeof(data) == TYPE_DICTIONARY,
		"status": status, "data": data}


func _request_id(kind: String) -> String:
	return str(run_state.run_id) + ":" + kind + ":" + Crypto.new().generate_random_bytes(8).hex_encode()


## Picture for any object: authored node, committed material art, painted sprite, or placeholder.
func texture_for(obj: Dictionary) -> Texture2D:
	var id := str(obj["id"])
	if object_textures.has(id):
		return object_textures[id]
	var authored := get_node_or_null("M2Objects/" + id) as Sprite2D
	if authored and not authored.has_meta("dynamic"):
		return authored.texture
	if obj.has("scene_node"):
		var scene_art := get_node_or_null(str(obj["scene_node"])) as Sprite2D
		if scene_art:
			return scene_art.texture
	var material_art := "res://assets/generated/materials/%s.png" % id
	if ResourceLoader.exists(material_art):
		object_textures[id] = _trimmed_texture((load(material_art) as Texture2D).get_image())
		return object_textures[id]
	var asset_id := str(obj.get("sprite_asset_id", ""))
	var cached := "user://assets/%s.png" % asset_id
	if not asset_id.is_empty() and FileAccess.file_exists(cached):
		var image := Image.load_from_file(cached)
		if image:
			object_textures[id] = _trimmed_texture(image)
			return object_textures[id]
	if not asset_id.is_empty() and not sprite_state.has(asset_id):
		_poll_sprite(id, asset_id)
	return null # Not painted yet (or it couldn't be): callers show a loading ring, never another object's art.


func is_placeholder(obj: Dictionary) -> bool:
	if obj.has("scene_node"):
		return false
	var authored := get_node_or_null("M2Objects/" + str(obj["id"])) as Sprite2D
	return not object_textures.has(str(obj["id"])) and not (authored and not authored.has_meta("dynamic"))


func sprite_status(obj: Dictionary) -> String:
	if not is_placeholder(obj):
		return "ready"
	var asset_id := str(obj.get("sprite_asset_id", ""))
	return "none" if asset_id.is_empty() else str(sprite_state.get(asset_id, "polling"))


func _trimmed_texture(image: Image) -> Texture2D:
	var started := Time.get_ticks_usec()
	var texture := _trimmed_texture_now(image)
	_prof("trim_texture", started)
	return texture


func _trimmed_texture_now(image: Image) -> Texture2D:
	if image.is_compressed():
		image.decompress()
	var used := image.get_used_rect()
	if used.size.x > 0 and used.size.y > 0:
		image = image.get_region(used)
	var longest := maxi(image.get_width(), image.get_height())
	if longest > 256:
		var ratio := 256.0 / float(longest)
		image.resize(maxi(1, roundi(image.get_width() * ratio)), maxi(1, roundi(image.get_height() * ratio)),
			Image.INTERPOLATE_LANCZOS)
	return ImageTexture.create_from_image(image)


func _apply_object_texture(sprite: Sprite2D, obj: Dictionary) -> void:
	var texture := texture_for(obj)
	var ring := sprite.get_node_or_null("LoadingRing")
	if texture == null:
		sprite.texture = null
		sprite.scale = Vector2.ONE
		if ring == null:
			ring = preload("res://scripts/loading_ring.gd").new()
			ring.name = "LoadingRing"
			sprite.add_child(ring)
		ring.missing = sprite_status(obj) in ["failed", "none"]
		ring.queue_redraw()
		return
	if ring:
		sprite.remove_child(ring)
		ring.queue_free()
	if sprite.texture == texture:
		return
	sprite.texture = texture
	var size := texture.get_size()
	# Trees stand tall and heavy things read larger; everyday items share one small size.
	var height := 150.0 if str(obj.get("feature", "")) == "tree" else OBJECT_HEIGHT if "carry" in obj.capabilities else 64.0
	var width := height * 1.3 if height > OBJECT_HEIGHT else OBJECT_MAX_WIDTH
	sprite.scale = Vector2.ONE * minf(height / size.y, width / size.x)
	# Tall things stand on their cell (so a tree falls from its base); small items stay centred.
	sprite.offset = Vector2.ZERO if height == OBJECT_HEIGHT else Vector2(0, -size.y * 0.5 + 12.0 / sprite.scale.y)


## Painting happens on the backend after the object exists; poll until it's ready.
func _poll_sprite(object_id: String, asset_id: String) -> void:
	sprite_state[asset_id] = "polling"
	for _attempt in 60:
		var reply := await _fetch_asset(asset_id)
		if run_state.is_empty():
			break
		if reply.status == 200:
			var image := Image.new()
			if image.load_png_from_buffer(reply.body) == OK:
				DirAccess.make_dir_recursive_absolute("user://assets")
				image.save_png("user://assets/%s.png" % asset_id)
				object_textures[object_id] = _trimmed_texture(image)
				sprite_state.erase(asset_id)
				_refresh_object_visuals()
				return
		if reply.status != 202:
			sprite_state[asset_id] = "failed" # Keep the placeholder; developer mode can retry.
			if run_state.get("mode", "") == "developer":
				ui.notify("Sprite for %s could not be painted (HTTP %s). See AI traces (F3)." % [object_id, reply.status])
			return
		await get_tree().create_timer(3.0).timeout
	sprite_state.erase(asset_id) # Gave up for now; the next display refresh polls again.


func _fetch_asset(asset_id: String) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)
	request.timeout = 15.0
	if request.request(SERVER + "/assets/" + asset_id) != OK:
		request.queue_free()
		return {"status": 0, "body": PackedByteArray()}
	var completed: Array = await request.request_completed
	request.queue_free()
	return {"status": int(completed[1]), "body": completed[3]}


func _refresh_object_visuals() -> void:
	if run_state.is_empty():
		return
	_sync_display()
	ui.refresh_icons()


## What a Try Something attempt can involve: carried items, anything intact within reach
## (whoever owns it, including trees), and people within reach.
func try_candidates() -> Array[Dictionary]:
	var carried: Array[Dictionary] = []
	var within_reach: Array[Dictionary] = []
	var here := Vector2(predicted_cell)
	for id in run_state.get("objects", {}):
		var obj: Dictionary = run_state.objects[id]
		if str(obj.condition) != "usable":
			continue
		if obj.holder_id == "player":
			carried.append(obj)
		elif obj.holder_id == null and here.distance_to(Vector2(int(obj.x), int(obj.y))) <= NEARBY_CELLS:
			within_reach.append(obj)
	for npc in run_state.get("npcs", []):
		if here.distance_to(Vector2(int(npc.x), int(npc.y))) <= NEARBY_CELLS:
			within_reach.append({"id": npc.id, "name": npc.name, "person": true, "alive": npc.get("alive", true)})
	carried.append_array(within_reach)
	return carried


func owner_name(obj: Dictionary) -> String:
	if obj.get("owner_id") == null:
		return ""
	if obj.owner_id == "player":
		return "you"
	for npc in run_state.get("npcs", []):
		if npc.id == obj.owner_id:
			return str(npc.name)
	return str(obj.owner_id)


## The one text line (GDD D-34): whatever the stranger typed goes to /act, which works out whether it is
## speech, a deed, both, waiting, giving up or walking away. Rounds play back in the dialogue bar;
## attempts outside a face-to-face walk, play out in the world, and land in the bar's log.
func act(text: String, target: String, selected_ids: Array) -> void:
	if request_busy or not gameplay_active or sync_error:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	if sync_error:
		request_busy = false
		return
	ui.bar.wait(text)
	var path := "/runs/" + str(run_state.run_id) + "/act"
	var body := {"text": text, "selected_ids": selected_ids, "expected_version": run_state.event_seq,
		"request_id": _request_id("act")}
	if not target.is_empty():
		body["target_id"] = target
	var reply := await _api(HTTPClient.METHOD_POST, path, body, 150.0)
	if not reply.ok and (int(reply.status) == 0 or int(reply.status) >= 500) and int(reply.status) != 503:
		reply = await _api(HTTPClient.METHOD_POST, path, body, 150.0)
	if not reply.ok:
		await _act_failed(reply)
		return
	var heard = reply.data.get("intent")
	ui.bar.last_intent = heard if typeof(heard) == TYPE_DICTIONARY else {}
	if typeof(reply.data.get("round")) == TYPE_DICTIONARY:
		await _play_round_reply(reply.data, target)
	elif reply.data.has("notice"):
		request_busy = false
		_accept_state(reply.data.state)
		ui.bar.note(str(reply.data.notice))
	else:
		await _play_attempt_reply(reply.data)


## An attempt outside a face-to-face: walk there, let it happen in the world, then the result.
func _play_attempt_reply(data: Dictionary) -> void:
	run_state = data.state
	last_trace = data.get("trace")
	var entry: Dictionary = run_state.last_action
	await _walk_along(entry.get("walk", [])) # Go there first, as the server already decided.
	_start_fall(entry) # Copy the falling thing before the sync hides it.
	_sync_display()
	_reveal_new_objects(entry)
	_play_harm(entry)
	if entry.category in ["success", "partial_success"]:
		effects.pickup_sound.play()
		player_visual.play_gesture("pickup" if entry.get("action") == "take" else "gesture")
		if typeof(entry.get("transformed")) == TYPE_DICTIONARY or typeof(entry.get("harm")) == TYPE_DICTIONARY:
			await get_tree().create_timer(1.2).timeout # Let the fall or the blow play out in view.
	request_busy = false
	ui.bar.result(entry, last_trace)


## A round: walk over first if the server planned it, then the bar plays it back line by line.
func _play_round_reply(data: Dictionary, target: String) -> void:
	last_trace = data.get("trace")
	var before_action = run_state.get("last_action")
	var round: Dictionary = data.round
	var walk: Array = round.get("walk", []) if typeof(round.get("walk")) == TYPE_ARRAY else []
	run_state = data.state
	if not walk.is_empty(): # Walked over to the person first.
		await _walk_along(walk)
	var entry = run_state.get("last_action")
	var did: bool = typeof(entry) == TYPE_DICTIONARY and entry != before_action
	if did:
		await _walk_along(entry.get("walk", []))
		_start_fall(entry)
	request_busy = false
	_sync_display()
	played_action = entry if did else {}
	# The bar plays the round back line by line; round_beat() gives each line its moment in the world.
	if in_encounter():
		ui.bar.open(target, "", round)
	else:
		ui.bar.ended(round)


## Nothing happened: say why honestly, reconcile with the server, and hand the words back.
func _act_failed(reply: Dictionary) -> void:
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	var problem := str(detail.get("message")) if typeof(detail) == TYPE_DICTIONARY and detail.has("message") \
		else _reply_problem(reply)
	var fresh := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id))
	if fresh.ok:
		_accept_state(fresh.data)
	else:
		sync_error = true
	request_busy = false
	ui.bar.problem(problem)

func _reply_problem(reply: Dictionary) -> String:
	if int(reply.status) == 0:
		return "The local simulation didn't answer in time. Your journey is safe."
	if int(reply.status) >= 500:
		return "The world stumbled (HTTP %s). Your journey is safe; try again." % reply.status
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	if typeof(detail) == TYPE_DICTIONARY and str(detail.get("reason", "")) == "in_progress":
		return "You're still working on your last attempt."
	if typeof(detail) == TYPE_STRING:
		return detail
	return "The attempt couldn't be completed (HTTP %s). Your journey is safe." % reply.status


func open_traces() -> void:
	if run_state.get("mode", "") != "developer" or request_busy:
		return
	var reply := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id) + "/traces?limit=10")
	if reply.ok:
		ui.show_traces(reply.data)
	else:
		ui.notify("Could not load AI traces (HTTP %s)." % reply.status)


func retry_sprite(asset_id: String) -> void:
	var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/assets/" + asset_id + "/retry")
	if reply.ok:
		sprite_state.erase(asset_id)
		_refresh_object_visuals()
		ui.notify("Repainting the sprite…")


func _save_settings() -> void:
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg") # Keep the UI settings and hints saved alongside.
	settings.set_value("feel", "zoom", camera_zoom)
	settings.set_value("feel", "volume", sound_volume)
	settings.save("user://presentation.cfg")
	AudioServer.set_bus_volume_db(0, linear_to_db(maxf(0.001, sound_volume)))
	AudioServer.set_bus_mute(0, sound_volume == 0.0)


## Nameplates fade in as you come close (or hover); the nearest thing is what E acts on.
func _update_nearby() -> void:
	if run_state.is_empty():
		return
	var hovered := str(ui.cursor.hover.get("id", ""))
	var best := ""
	var best_distance := 90.0
	for id in run_state.get("objects", {}):
		var obj: Dictionary = run_state.objects[id]
		if obj.holder_id != null or str(obj.get("condition", "usable")) != "usable" or obj.has("scene_node"):
			continue
		var distance := player.position.distance_to(_cell_center(int(obj.x), int(obj.y)))
		if distance < best_distance:
			best_distance = distance
			best = str(id)
	for npc in run_state.npcs:
		var npc_actor := get_node_or_null("NPCs/" + str(npc.id)) as Node2D
		var npc_position := npc_actor.position if npc_actor else _cell_center(int(npc.x), int(npc.y))
		var distance := player.position.distance_to(npc_position)
		if distance < best_distance:
			best_distance = distance
			best = str(npc.id)
		var plate := get_node_or_null("NPCs/" + str(npc.id) + "/Nameplate") as Label
		if plate:
			plate.modulate.a = 1.0 if hovered == str(npc.id) else clampf((240 - distance) / 90, 0, 1)
	nearby_target = best
	ui.hud.area.text = "THE CITY GATE" if player.position.y < 600 else "THE CRAFTSMEN'S ROW" if player.position.y < 1200 else "THE WAYSIDE INN" if player.position.y < 1800 else "THE SOUTH ROAD"

## E: act on whatever is nearest, as a left click on it would.
func _interact() -> void:
	if nearby_target.is_empty() or request_busy:
		return
	_left_click(ui.cursor.describe(nearby_target))


## Left click in the world: talk to a person, pick up (or steal) a thing, or point at anything else
## in the dialogue bar. With words already in the line (or face to face), clicking points instead.
func _left_click(hover: Dictionary) -> void:
	if request_busy or not gameplay_active:
		return
	if hover.is_empty():
		if ui.bar.visible and not ui.bar.showing_encounter() and ui.bar.line.text.strip_edges().is_empty():
			ui.bar.close()
		return
	var id := str(hover.id)
	if not hover.get("reachable", true):
		ui.notify("%s is too far away. Walk closer." % str(hover.name).capitalize())
		return
	ui.hud.dismiss_hint("controls")
	if ui.bar.visible and (ui.bar.showing_encounter() or not ui.bar.line.text.strip_edges().is_empty()):
		if hover.kind == "person" and hover.action == "talk":
			ui.bar.address(id)
		else:
			ui.bar.add_reference(id)
		return
	match str(hover.action):
		"talk":
			ui.bar.open(id)
		"take":
			ui.bar.close()
			_quick_action("take", id)
		"look":
			ui.card.show_for(id)
		_:
			ui.bar.open(id)

## One exchange in a conversation: Jev decides the reply on the server and the voice phrases it.
func say_to(npc_id: String, text: String) -> void:
	await act(text, npc_id, [])


func in_encounter() -> bool:
	return typeof(run_state.get("encounter")) == TYPE_DICTIONARY


## A plain round move without words: walking away (Esc), or waiting / giving up from the tools.
## Face to face, everyone else's committed actions resolve at the same moment on the server.
func encounter_act(kind: String, text: String, target: String) -> void:
	if request_busy or not gameplay_active or sync_error:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	ui.bar.wait({"leave": "You walk away.", "wait": "You wait.", "yield": "You give up."}.get(kind, text))
	var path := "/runs/" + str(run_state.run_id) + "/encounter/act"
	var body := {"kind": kind, "text": text, "selected_ids": [], "expected_version": run_state.event_seq,
		"request_id": _request_id("round")}
	if not target.is_empty():
		body["target_id"] = target
	var reply := await _api(HTTPClient.METHOD_POST, path, body, 150.0)
	if not reply.ok and (int(reply.status) == 0 or int(reply.status) >= 500) and int(reply.status) != 503:
		reply = await _api(HTTPClient.METHOD_POST, path, body, 150.0)
	if reply.ok:
		await _play_round_reply(reply.data, target)
	else:
		await _act_failed(reply)

var played_action: Dictionary = {} # The stranger's Try Something in the round being played back.


## One line of a round, as it happens in the world: a blow lands, someone gestures as they speak.
func round_beat(entry: Dictionary) -> void:
	var who := str(entry.get("who", ""))
	if who == "player":
		if entry.get("kind") == "do" and not played_action.is_empty():
			_reveal_new_objects(played_action)
			_play_harm(played_action)
			if played_action.category in ["success", "partial_success"]:
				effects.pickup_sound.play()
				player_visual.play_gesture("pickup" if played_action.get("action") == "take" else "gesture")
		return
	var actor := get_node_or_null("NPCs/%s/PaintedActor" % who)
	if actor and entry.get("kind") in ["strike", "reply", "interject", "shout_for_help", "whistle", "attack", "arrive"]:
		actor.play_gesture("gesture")
	if entry.get("kind") == "strike" and not "misses" in str(entry.text):
		var npc_actor := get_node_or_null("NPCs/" + who) as Node2D
		player_visual.hurt(1.0 if npc_actor == null or npc_actor.position.x <= player.position.x else -1.0)


## After the round has played out: the death screen if the stranger fell.
func round_played() -> void:
	played_action = {}
	var last = run_state.get("last_round")
	if typeof(last) == TYPE_DICTIONARY and last.get("arrested", false) and run_state["player"].get("alive", true):
		request_busy = true # Nothing else happens while the guards march you off.
		await get_tree().create_timer(1.8).timeout # Time to read what happened.
		ui.bar.close()
		ui.close_modal_now()
		await ui.fade(1.0)
		predicted_cell = Vector2i(int(run_state["player"]["x"]), int(run_state["player"]["y"]))
		player.position = _cell_center(predicted_cell.x, predicted_cell.y)
		camera.reset_smoothing()
		_sync_display()
		await get_tree().create_timer(0.5).timeout
		await ui.fade(0.0)
		request_busy = false
		ui.notify("The guards march you back down the south road. You're not welcome at the gate for a while.")
	if not run_state["player"].get("alive", true) and gameplay_active:
		gameplay_active = false
		move_queue.clear()
		player_visual.die(1.0)
		await get_tree().create_timer(1.6).timeout
		ui.show_death(_death_reason())


## Pick up (or steal) and put down: decided by code on the server, which plans the walk there first.
func _quick_action(verb: String, id: String) -> void:
	if request_busy or not gameplay_active or sync_error:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	if sync_error:
		request_busy = false
		return
	var body := {"verb": verb, "object_id": id, "expected_version": run_state.event_seq,
		"request_id": _request_id(verb)}
	var reply := await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/quick", body)
	if not reply.ok and (int(reply.status) == 0 or int(reply.status) >= 500):
		reply = await _api(HTTPClient.METHOD_POST, "/runs/" + str(run_state.run_id) + "/quick", body)
	if reply.ok:
		run_state = reply.data.state
		var entry: Dictionary = run_state.last_action
		await _walk_along(entry.get("walk", []))
		request_busy = false
		_sync_display()
		var claims: Array = entry.get("property", [])
		if entry.category == "success" and not claims.is_empty():
			var owner := str(ui.npc_record(str(claims[0].owner_id)).get("name", "someone"))
			ui.notify("You take the %s. It belongs to %s." % [claims[0].name, owner])
		else:
			ui.notify(str(entry.reason))
		if entry.category == "success":
			effects.pickup_sound.play()
			player_visual.play_gesture("pickup" if verb == "take" else "gesture")
			if verb == "take":
				ui.hud.show_hint("pack", "It's in your pack (bottom of the screen). Drag it onto someone or something to use it; right-click it to look closer.")
		if ui.modal_kind == "inventory":
			ui.open_inventory()
		return
	# Reconcile a lost response before allowing another world-changing action.
	var detail = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
	var fresh := await _api(HTTPClient.METHOD_GET, "/runs/" + str(run_state.run_id))
	if fresh.ok:
		run_state = fresh.data
		_sync_display()
	else:
		sync_error = true
	request_busy = false
	ui.notify("Not now: deal with who's in front of you first." if typeof(detail) == TYPE_DICTIONARY
		and str(detail.get("reason", "")) == "encounter_active" else "Could not confirm the action. Your saved journey is preserved.")

func _unhandled_input(event: InputEvent) -> void:
	if run_state.is_empty():
		return
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP or event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			if gameplay_active and not ui.modal.visible:
				camera_zoom = clampf(camera_zoom + (0.05 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -0.05), 0.75, 1.25)
				_save_settings()
			return
		if not gameplay_active or ui.modal.visible or menu.visible:
			return
		var hover: Dictionary = ui.cursor.pick(get_global_mouse_position())
		if event.button_index == MOUSE_BUTTON_LEFT:
			_left_click(hover)
		elif event.button_index == MOUSE_BUTTON_RIGHT and not hover.is_empty():
			ui.card.show_for(str(hover.id))
		get_viewport().set_input_as_handled()
		return
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	match event.keycode:
		KEY_ESCAPE:
			if ui.card.visible:
				ui.card.hide()
			elif ui.modal.visible:
				ui.close_modal()
			elif ui.bar.visible:
				ui.bar.escape()
			else:
				ui.open_menu()
		KEY_F3:
			if run_state.mode == "developer":
				trace_panel.visible = not trace_panel.visible
		KEY_F4:
			if run_state.mode == "developer" and not ui.modal.visible:
				open_traces()
		KEY_J:
			if ui.modal_kind == "journal":
				ui.close_modal()
			elif gameplay_active:
				ui.open_journal()
		KEY_I:
			if ui.modal_kind == "inventory":
				ui.close_modal()
			elif gameplay_active:
				ui.open_inventory()
		KEY_E:
			if gameplay_active and not ui.modal.visible and not ui.bar.visible:
				_interact()
		KEY_T, KEY_ENTER, KEY_KP_ENTER:
			if gameplay_active and not ui.modal.visible:
				ui.bar.open()
		_:
			return
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
	ui.leave_run()
	run_state = {}
	menu.show()
	ui.leave_run()
	effects.has_target = false
	trace_panel.hide()
	victory_panel.hide()
	message.text = "Your journey is saved."
