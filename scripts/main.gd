extends Node2D

const UITheme := preload("res://scripts/ui/ui_theme.gd")
const Net := preload("res://scripts/net.gd")
const ObjectArt := preload("res://scripts/object_art.gd")
const WorldView := preload("res://scripts/world_view.gd")
const PlayerInput := preload("res://scripts/player_input.gd")
const Actions := preload("res://scripts/actions.gd")

const CELL := 32.0
const WORLD_SIZE := Vector2(3072, 2304)
const WALK_SPEED := 230.0 # 7.1875 cells/second, shared with the service.
const RUN_SPEED := 368.0 # 11.5 cells/second while Shift is held.
@onready var player: CharacterBody2D = $Player
@onready var player_sprite: Sprite2D = $Player/Sprite2D
@onready var player_visual: Node2D = $Player/PaintedActor
@onready var camera: Camera2D = $Player/Camera2D
@onready var gate_shape: CollisionShape2D = $WorldCollision/ClosedGate/CollisionShape2D
@onready var gate_sprite: Sprite2D = $Map/Gate
@onready var gate_opening: ColorRect = $Map/GateOpening

## The game's parts (children of this node): the service, pictures, the world on screen, the player's input
## and actions. This script is the journey itself: its state, the movement and thinking lanes, the camera.
var net: Net
var art: ObjectArt
var view: WorldView
var controls: PlayerInput
var actions: Actions
var run_state: Dictionary = {}
var request_busy := false
var gameplay_active := false
var movement_sync_active := false
var move_queue: Array[Dictionary] = []
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
var footstep_distance := 0.0
var camera_zoom := 1.0
var sound_volume := 0.7
var sync_error := false
var ai_status: Dictionary = {}
var last_trace = null # Developer runs receive the judge trace with each attempt.
var hurt_flash: TextureRect # Red at the screen's edges when you're struck.
var shake := 0.0 # The camera's shake when you're hit (D-55), in pixels; it dies away.
var shake_jitter := Vector2.ZERO
var fight: Node # Hands, gear, blows and missiles on screen (D-49): scripts/fight_view.gd.

var scripted_walk := false
## Two thinking lanes (D-39): reactions never wait behind people planning their day or remembering.
var thinking_lanes := {"react": false, "village": false}
var thinking_active: bool:
	get:
		return thinking_lanes.react or thinking_lanes.village
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
func _ready() -> void:
	net = Net.new()
	net.name = "Net"
	net.game = self
	add_child(net)
	art = ObjectArt.new()
	art.name = "ObjectArt"
	art.game = self
	add_child(art)
	view = WorldView.new()
	view.name = "WorldView"
	view.game = self
	add_child(view)
	controls = PlayerInput.new()
	controls.name = "PlayerInput"
	controls.game = self
	add_child(controls)
	actions = Actions.new()
	actions.name = "Actions"
	actions.game = self
	add_child(actions)
	net.server = net.address()
	$NPCPreview.hide()
	$M2Objects.hide()
	_build_ui()
	_extend_ground()
	effects = preload("res://scripts/feel_effects.gd").new()
	effects.z_index = -1
	add_child(effects)
	fight = preload("res://scripts/fight_view.gd").new()
	fight.name = "FightView"
	fight.game = self
	add_child(fight)
	var settings := ConfigFile.new()
	if settings.load("user://presentation.cfg") == OK:
		camera_zoom = clampf(float(settings.get_value("feel", "zoom", 1.0)), 0.75, 1.25)
		sound_volume = clampf(float(settings.get_value("feel", "volume", 0.7)), 0.0, 1.0)
	save_settings()
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


func cell_center(x: int, y: int) -> Vector2:
	return Vector2((float(x) + 0.5) * CELL, (float(y) + 0.5) * CELL)


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	ui = preload("res://scripts/game_ui.gd").new()
	layer.add_child(ui)
	ui.build(self)
	var edges := Gradient.new()
	edges.set_color(0, Color(0.7, 0.05, 0.02, 0.0))
	edges.set_color(1, Color(0.7, 0.05, 0.02, 0.85))
	edges.set_offset(0, 0.55)
	var fill := GradientTexture2D.new()
	fill.gradient = edges
	fill.fill = GradientTexture2D.FILL_RADIAL
	fill.fill_from = Vector2(0.5, 0.5)
	fill.fill_to = Vector2(1.05, 1.05)
	hurt_flash = TextureRect.new()
	hurt_flash.texture = fill
	hurt_flash.stretch_mode = TextureRect.STRETCH_SCALE
	hurt_flash.set_anchors_preset(Control.PRESET_FULL_RECT)
	hurt_flash.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hurt_flash.modulate.a = 0.0
	layer.add_child(hurt_flash)


func start(mode: String, scenario := "village") -> void:
	if request_busy:
		return
	request_busy = true
	message.text = "Connecting to local simulation…"
	var reply := await net.api(HTTPClient.METHOD_POST, "/runs", {"mode": mode, "scenario": scenario})
	request_busy = false
	if not reply["ok"]:
		message.text = "Backend unavailable. Run tools/run_m0.ps1, then try again."
		return
	enter_run(reply["data"])


func _check_health() -> void:
	var reply := await net.api(HTTPClient.METHOD_GET, "/health")
	if reply["ok"] and typeof(reply["data"].get("ai")) == TYPE_DICTIONARY:
		ai_status = reply["data"]["ai"]
	if menu.visible:
		var settings := ConfigFile.new()
		var tutorial_done: bool = settings.load("user://presentation.cfg") == OK and settings.get_value("tutorial", "done", false)
		message.text = ("Local simulation ready. Start or resume a run." + (
			"" if tutorial_done else "\nNew here? Start with the tutorial.") + (
			"" if ai_ready() else "\nAI crafting is off: add OPENAI_API_KEY to backend/.env and restart the backend.")
			) if reply["ok"] else "Start the local backend first: tools/run_m0.ps1"


func ai_ready() -> bool:
	return bool(ai_status.get("judge", false))


func resume() -> void:
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
	var reply := await net.api(HTTPClient.METHOD_GET, "/runs/" + str(saved["run_id"]))
	request_busy = false
	if not reply["ok"]:
		message.text = "Could not resume. Check that the backend and save database are available."
		return
	enter_run(reply["data"])


func enter_run(state: Dictionary, save_pointer := true) -> void:
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
	view.apply_building_geometry(int(state.get("geometry_version", 1)))
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
	player.position = cell_center(int(state["player"]["x"]), int(state["player"]["y"]))
	player_visual.revive()
	camera.reset_smoothing()
	menu.hide()
	ui.device.refresh()
	ui.guide.refresh()
	ui.layers.refresh()
	view.spawn_people()
	$M2Objects.visible = not run_state.get("objects", {}).is_empty()
	view.sync()
	ui.enter_run(state)
	if int(state.get("geometry_version", 1)) < 2:
		ui.notify("Earlier map restored. Begin a new journey to test building and tree collisions.")
	if state["inside_city"]:
		show_victory()
		gameplay_active = false
	elif not state["player"].get("alive", true):
		gameplay_active = false
		player_visual.lie_dead()
		ui.screens.show_death(death_reason())
	else:
		gameplay_active = true


func facing_for(direction: Vector2) -> int:
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


## A blow lands on you (D-55): the view jolts, then settles.
func shake_camera(strength := 9.0) -> void:
	shake = maxf(shake, strength)


func _process(delta: float) -> void:
	camera.offset -= shake_jitter
	shake = move_toward(shake, 0.0, delta * 30.0)
	shake_jitter = Vector2(randf_range(-1.0, 1.0), randf_range(-1.0, 1.0)) * shake if shake > 0.0 else Vector2.ZERO
	camera.offset += shake_jitter


func _physics_process(delta: float) -> void:
	camera.zoom = camera.zoom.lerp(Vector2.ONE * camera_zoom, minf(1.0, delta * 10))
	# The view shifts so you stay in sight above the dialogue bar or the pack.
	var lift := _camera_lift()
	camera.offset.y = lerpf(camera.offset.y, lift, minf(1.0, delta * 6.0))
	var started := Time.get_ticks_usec()
	controls.update_nearby()
	_prof("update_target", started)
	if gameplay_active and not sync_error: # Thinking never pauses: not for the dialogue bar, a panel or a walk.
		for lane in ["react", "village"]:
			if not thinking_lanes[lane] and _minds_pending(lane):
				_flush_minds(lane)
	if in_encounter() and gameplay_active and not request_busy and not ui.bar.showing_encounter() \
			and ui.modal_kind != "death":
		ui.close_modal_now()
		ui.bar.open()
	if in_fight() and gameplay_active and not sync_error and (request_busy or ui.blocks_movement()) \
			and not ui.guide.is_open(): # The tutorial's cards stop even a fight (D-52).
		# A fight doesn't wait while you type or think: the clock and the blows run on (D-41).
		view.animate_people(delta)
		clock_pending_ms += delta * 1000.0
		if not movement_sync_active and clock_pending_ms >= 500.0:
			_flush_moves()
	if not gameplay_active or request_busy or ui.blocks_movement() or sync_error:
		if scripted_walk: # _walk_along is moving the player.
			return
		player.velocity = Vector2.ZERO
		player_sprite.frame = _cardinal_fallback(facing_row) * 3
		player_visual.set_motion(facing_row, "idle", 0.0, delta)
		return
	started = Time.get_ticks_usec()
	view.animate_people(delta)
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
		facing_row = facing_for(visual_direction)
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
	var gait := "run" if is_running and travelled > 0.15 else "walk" if travelled > 0.15 else "idle"
	player_visual.set_motion(facing_row, gait, travelled, delta)
	var cell := Vector2i(int(floor(player.position.x / CELL)), int(floor(player.position.y / CELL)))
	if cell != predicted_cell:
		move_queue.append({"cell": cell, "running": is_running})
		predicted_cell = cell
		ui.note_cell(cell)
		if not movement_sync_active:
			_flush_moves()
	if not movement_sync_active and int(run_state.get("seed_version", 1)) >= 3 and clock_pending_ms >= 500.0:
		_flush_moves()


## Movement lane: the player's steps (batched) and the clock, one request at a time.
## People's thinking runs separately in _flush_minds, so a model never holds up walking or time.
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
				"request_id": request_id("move")}
		else:
			elapsed_ms = mini(floori(clock_pending_ms), 1000)
			clock_pending_ms -= float(elapsed_ms)
			path = "/explore"
			body = {"elapsed_ms": elapsed_ms, "expected_version": run_state["event_seq"],
				"request_id": request_id("explore")}
		var reply := await net.post(run_path(path), body)
		if reply["ok"]:
			accept_state(reply["data"]["state"])
			if run_state["inside_city"]:
				gameplay_active = false
				show_victory()
				move_queue.clear()
		else:
			if not sending_move:
				clock_pending_ms += float(elapsed_ms)
			move_queue.clear()
			var blocked_state = reply.data.get("state") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
			if typeof(blocked_state) == TYPE_DICTIONARY:
				accept_state(blocked_state) # The legal steps before the blocked one were kept.
			else:
				sync_error = true
				await reconcile()
			snap_to_server()
			var said = reply.data.get("detail") if typeof(reply.get("data")) == TYPE_DICTIONARY else null
			ui.notify("Connection lost. Pause and resume your journey to reconnect." if sync_error else
				(str(said) if typeof(said) == TYPE_STRING and "gateway" in str(said) else "That path is blocked.")
				if sending_move else "The village clock is reconnecting.")
			break
	movement_sync_active = false


## Thinking lane: people with something on their mind decide (the decider), alongside the movement lane.
func _flush_minds(lane := "react") -> void:
	if thinking_lanes[lane]:
		return
	thinking_lanes[lane] = true
	while _minds_pending(lane):
		var body := {"expected_version": run_state["event_seq"], "request_id": request_id("think"), "lane": lane}
		var reply := await net.post(run_path("/think"), body, 40.0)
		if not reply["ok"]:
			await get_tree().create_timer(1.0).timeout # e.g. another think still finishing; try again shortly.
			continue
		accept_state(reply["data"]["state"])
	thinking_lanes[lane] = false


## Replies from the two lanes can arrive in either order; the newest world state wins
## (the server applies events one at a time, so a later event already includes the earlier ones).
func accept_state(new_state: Dictionary) -> void:
	if int(new_state.get("event_seq", 0)) < int(run_state.get("event_seq", 0)):
		return
	if run_state.has("run_id") and new_state.get("run_id") != run_state.get("run_id"):
		return # A late reply from a journey that has since been left (e.g. its thinking lane).
	if last_state_usec > 0:
		_prof_max("longest_gap_between_updates_ms", (Time.get_ticks_usec() - last_state_usec) / 1000.0)
	last_state_usec = Time.get_ticks_usec()
	var before := run_state
	run_state = new_state
	view.sync()
	fight.sync()
	ui.device.refresh()
	ui.guide.refresh()
	ui.layers.refresh()
	var was_tutorial = before.get("tutorial")
	var now_tutorial = run_state.get("tutorial")
	if typeof(was_tutorial) == TYPE_DICTIONARY and typeof(now_tutorial) == TYPE_DICTIONARY \
			and not was_tutorial.get("done", false) and now_tutorial.get("done", false):
		ui.device.closing_card() # The first morning is over (D-50).
	view.react_to(before)


func toggle_gate() -> void:
	if run_state.get("mode", "normal") != "developer" or request_busy or movement_sync_active or not move_queue.is_empty():
		return
	request_busy = true
	var body := {
		"open": not run_state["gate_open"], "expected_version": run_state["event_seq"],
		"request_id": str(run_state["run_id"]) + ":gate:" + str(run_state["event_seq"] + 1)
	}
	var reply := await net.api(HTTPClient.METHOD_POST, run_path("/dev/gate"), body)
	if reply["ok"]:
		run_state = reply["data"]["state"]
		view.sync()
	request_busy = false


## Something to think about in this lane: reactions (react) or the village's own life (village).
func _minds_pending(lane := "any") -> bool:
	if not gameplay_active or run_state.is_empty():
		return false
	var reacting := ["decide", "fight"]
	return run_state.get("pending_minds", []).any(func(p) -> bool:
		return lane == "any" or (str(p.get("kind", "")) in reacting) == (lane == "react"))


func in_fight() -> bool:
	return typeof(run_state.get("fight")) == TYPE_DICTIONARY


func show_victory() -> void:
	var admitted = run_state.get("admitted")
	var lines := PackedStringArray()
	if typeof(admitted) == TYPE_DICTIONARY:
		var by := str(admitted.get("by", ""))
		lines.append("Captain Roderic let you through the gate." if by == "npc_roderic_vale" else
			"%s let you through the gate, on their own say-so." % str(ui.npc_record(by).get("name", "A guard")))
		var because: Array = admitted.get("because", [])
		if not because.is_empty():
			lines.append("What weighed with them:")
			for reason in because:
				lines.append("• " + str(reason))
	elif str(run_state.get("entered_by", "")) == "unbarred":
		lines.append("You lifted the bar off the gate and walked in, with no guard left to stop you.")
	else:
		lines.append("You found your own way in.")
	victory_route.text = "\n".join(lines)
	victory_panel.show()


func death_reason() -> String:
	var journal: Array = run_state.get("journal", [])
	for index in range(journal.size() - 1, -1, -1):
		if journal[index].get("kind") == "npc_attack" and journal[index].get("result") == "killed":
			return str(journal[index].reason)
		if journal[index].get("kind") == "fight" and journal[index].get("category") == "killed":
			return str(journal[index].reason)
	return "You died."


func rewind() -> void:
	if request_busy:
		return
	request_busy = true
	var reply := await net.api(HTTPClient.METHOD_POST, run_path("/rewind"), {}, 30.0)
	request_busy = false
	if reply.ok and typeof(reply.data) == TYPE_DICTIONARY:
		enter_run(reply.data)
		ui.notify("You are back, just before the trouble began.")
	else:
		ui.notify("Could not rewind the journey (HTTP %s)." % reply.status)


## This journey's path on the service: run_path("/act") is /runs/<id>/act.
func run_path(suffix := "") -> String:
	return "/runs/" + str(run_state["run_id"]) + suffix


## Hold the journey for one world-changing action: after the movement lane's request in flight, and never while
## out of step with the service. Whether it's ours (request_busy is set until the action lets it go).
func claim() -> bool:
	if request_busy or not gameplay_active or sync_error:
		return false
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	if sync_error:
		request_busy = false
		return false
	return true


## Back in step with the service after a reply went astray: its world as it is now. Whether that worked.
func reconcile() -> bool:
	var fresh := await net.api(HTTPClient.METHOD_GET, run_path())
	if fresh.ok:
		accept_state(fresh.data)
	sync_error = not fresh.ok
	return fresh.ok


## The stranger is where the service says (a blocked step undone, marched off by the guards).
func snap_to_server() -> void:
	predicted_cell = Vector2i(int(run_state["player"]["x"]), int(run_state["player"]["y"]))
	player.position = cell_center(predicted_cell.x, predicted_cell.y)


## The stranger falls: the world stops for them, they collapse, and the death screen follows.
func die() -> void:
	gameplay_active = false
	move_queue.clear()
	player_visual.die(1.0)
	await get_tree().create_timer(1.6).timeout
	ui.screens.show_death(death_reason())


func request_id(kind: String) -> String:
	return str(run_state.run_id) + ":" + kind + ":" + Crypto.new().generate_random_bytes(8).hex_encode()


func open_traces() -> void:
	if run_state.get("mode", "") != "developer" or request_busy:
		return
	var reply := await net.api(HTTPClient.METHOD_GET, run_path("/traces?limit=10"))
	if reply.ok:
		ui.dev.show_traces(reply.data)
	else:
		ui.notify("Could not load AI traces (HTTP %s)." % reply.status)


func save_settings() -> void:
	var settings := ConfigFile.new()
	settings.load("user://presentation.cfg") # Keep the UI settings and hints saved alongside.
	settings.set_value("feel", "zoom", camera_zoom)
	settings.set_value("feel", "volume", sound_volume)
	settings.save("user://presentation.cfg")
	AudioServer.set_bus_volume_db(0, linear_to_db(maxf(0.001, sound_volume)))
	AudioServer.set_bus_mute(0, sound_volume == 0.0)


func in_encounter() -> bool:
	return typeof(run_state.get("encounter")) == TYPE_DICTIONARY


func back_to_menu() -> void:
	if request_busy:
		return
	request_busy = true
	while movement_sync_active:
		await get_tree().process_frame
	gameplay_active = false
	if not run_state.is_empty():
		await net.api(HTTPClient.METHOD_POST, run_path("/checkpoint"))
	request_busy = false
	ui.leave_run()
	run_state = {}
	menu.show()
	ui.leave_run()
	effects.has_target = false
	trace_panel.hide()
	victory_panel.hide()
	message.text = "Your journey is saved."
