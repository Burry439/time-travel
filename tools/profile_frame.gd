extends SceneTree
## Frame-time profile of the real scene: idle, walking, running, and people reacting to a punch.
## Needs the backend running live (the reaction phase uses the real judge and decider, about $0.002):
##   ./tools/run_m0.ps1
##   Godot_v4.7.2-stable_win64_console.exe --path . --script res://tools/profile_frame.gd
## Runs with vsync off so frame times show real work, not the monitor's refresh.
var scene: Node2D
var phase := ""
var frame_ms: Dictionary = {} # phase -> Array of frame milliseconds
var last_usec := 0
var blocked := {}


func _initialize() -> void:
	call_deferred("_run")


func _process(_delta: float) -> bool:
	var now := Time.get_ticks_usec()
	if not phase.is_empty() and last_usec > 0:
		frame_ms[phase].append((now - last_usec) / 1000.0)
	last_usec = now
	return false


func _hold(actions: Array, seconds: float) -> void:
	for action in actions:
		Input.action_press(action)
	await create_timer(seconds).timeout
	for action in actions:
		Input.action_release(action)


func _record(name: String, body: Callable) -> void:
	scene.prof.clear()
	scene.prof_max.clear()
	scene.last_state_usec = 0
	frame_ms[name] = []
	phase = name
	await body.call()
	phase = ""
	var times: Array = frame_ms[name]
	times.sort()
	var pick := func(q: float) -> float: return times[mini(times.size() - 1, int(times.size() * q))]
	var slow := times.filter(func(t: float) -> bool: return t > 16.7).size()
	print("\n== %s: %d frames  p50 %.1f ms  p95 %.1f ms  p99 %.1f ms  max %.1f ms  (%d over 16.7 ms)" % [
		name, times.size(), pick.call(0.5), pick.call(0.95), pick.call(0.99), times[-1], slow])
	var keys: Array = scene.prof.keys()
	keys.sort_custom(func(a, b) -> bool: return scene.prof[a][1] > scene.prof[b][1])
	for key in keys:
		var entry: Array = scene.prof[key]
		print("   %-22s calls %5d  total %7.1f ms  avg %6.3f ms%s" % [key, entry[0], entry[1] / 1000.0,
			entry[1] / 1000.0 / maxi(1, entry[0]), ("  avg %.1f KB" % (entry[2] / 1024.0 / entry[0])) if entry[2] else ""])
	for key in scene.prof_max:
		print("   %-22s %.0f ms" % [key, scene.prof_max[key]])


## Walk with real, server-validated moves along a shortest path (clock paused so moves stay in order).
func _walk(to: Vector2i) -> void:
	var geometry: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://data/world_geometry.json"))
	for item in geometry.buildings + geometry.obstacles:
		for x in range(int(item.cells[0]), int(item.cells[0]) + int(item.cells[2])):
			for y in range(int(item.cells[1]), int(item.cells[1]) + int(item.cells[3])):
				blocked[Vector2i(x, y)] = true
	scene.gameplay_active = false
	var start := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	var previous := {start: start}
	var frontier: Array[Vector2i] = [start]
	while not frontier.is_empty() and not previous.has(to):
		var cell: Vector2i = frontier.pop_front()
		for step in [Vector2i.RIGHT, Vector2i.LEFT, Vector2i.DOWN, Vector2i.UP]:
			var next: Vector2i = cell + step
			if not previous.has(next) and not blocked.has(next) and next.x >= 0 and next.x < 96 \
					and next.y >= 9 and next.y < 72:
				previous[next] = cell
				frontier.append(next)
	var route: Array[Vector2i] = []
	var cursor := to
	while cursor != start:
		route.push_front(cursor)
		cursor = previous[cursor]
	var state: Dictionary = scene.run_state
	for cell in route:
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % state.run_id,
			{"x": cell.x, "y": cell.y, "expected_version": state.event_seq, "request_id": "walk-%s" % state.event_seq})
		state = reply.data.state
	scene._enter_run(state, false)
	await create_timer(0.5).timeout


func _run() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await create_timer(1.0).timeout
	await _record("idle", func() -> void: await create_timer(8.0).timeout)
	await _record("walking", func() -> void:
		await _hold(["move_up"], 4.0)
		await _hold(["move_left"], 3.0)
		await _hold(["move_down"], 4.0))
	await _record("running", func() -> void:
		await _hold(["move_up", "run"], 3.0)
		await _hold(["move_right", "run"], 2.5)
		await _hold(["move_down", "run"], 3.0))
	# People reacting: punch Jory at the smithy (Mara watching), then run away while they react.
	await _walk(Vector2i(23, 29))
	await scene.act("punch Jory hard in the face", "", [])
	scene.ui.bar.close()
	await _record("reacting, running away", func() -> void:
		await _hold(["move_down", "run"], 2.0)
		await _hold(["move_right", "run"], 3.0)
		await _hold(["move_down", "run"], 2.0)
		await _hold(["move_right", "run"], 3.0))
	print("   player alive at end: ", scene.run_state.player.get("alive", true))
	print("\nPROFILE DONE")
	quit(0)
