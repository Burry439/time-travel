extends SceneTree
## Replays a player's situation: opens a saved journey (use tools/clone_run.py for a copy) and plays it for a while:
## standing, walking about, swinging both hands at nothing and at people, while printing frame times, node counts
## and memory every 5 s. For hunting slowdowns and crashes the player saw.
##   Godot_v4.7.2-stable_win64_console.exe --path . --script res://tools/probe_run.gd -- --run=RUN_ID [--seconds=60]
var scene: Node2D
var frames: Array = []
var last_usec := 0
var run_id := ""
var seconds := 60.0


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--run="):
			run_id = arg.get_slice("=", 1)
		elif arg.begins_with("--seconds="):
			seconds = float(arg.get_slice("=", 1))
	call_deferred("_run")


func _process(_delta: float) -> bool:
	var now := Time.get_ticks_usec()
	if last_usec > 0:
		frames.append((now - last_usec) / 1000.0)
	last_usec = now
	return false


func _report(label: String) -> void:
	var times := frames.duplicate()
	frames.clear()
	times.sort()
	if times.is_empty():
		return
	var pick := func(q: float) -> float: return times[mini(times.size() - 1, int(times.size() * q))]
	print(("%-12s frames %4d  p50 %5.1f  p95 %6.1f  max %7.1f ms | nodes %5d  objects %6d  orphans %4d | "
		+ "mem %6.1f MB | seq %d  fight %s  health %d") % [
		label, times.size(), pick.call(0.5), pick.call(0.95), times[-1],
		Performance.get_monitor(Performance.OBJECT_NODE_COUNT), Performance.get_monitor(Performance.OBJECT_COUNT),
		Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0, int(scene.run_state.get("event_seq", 0)),
		"yes" if scene.in_fight() else "no", int(scene.run_state.player.get("health", 0))])
	var keys: Array = scene.prof.keys()
	keys.sort_custom(func(a, b) -> bool: return scene.prof[a][1] > scene.prof[b][1])
	for key in keys.slice(0, 6):
		var entry: Array = scene.prof[key]
		print("     %-26s calls %4d  total %8.1f ms  avg %7.2f ms" % [key, entry[0], entry[1] / 1000.0,
			entry[1] / 1000.0 / maxi(1, entry[0])])
	scene.prof.clear()


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var loaded: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/runs/" + run_id)
	if not loaded.ok:
		push_error("PROBE FAILED: could not load the journey " + run_id)
		quit(1)
		return
	scene.enter_run(loaded.data, false)
	var started := Time.get_ticks_msec()
	var next_report := 5.0
	var moves := ["move_left", "move_up", "move_right", "move_down"]
	var step := 0
	while (Time.get_ticks_msec() - started) / 1000.0 < seconds:
		var elapsed := (Time.get_ticks_msec() - started) / 1000.0
		if elapsed > 10.0: # After 10 s standing: walk a little, then swing each hand.
			var action: String = moves[step % moves.size()]
			Input.action_press(action)
			await create_timer(0.6).timeout
			Input.action_release(action)
			scene.fight.strike("right")
			await create_timer(0.5).timeout
			scene.fight.strike("left")
			step += 1
		await create_timer(0.4).timeout
		if (Time.get_ticks_msec() - started) / 1000.0 >= next_report:
			_report("t=%ds" % int(next_report))
			next_report += 5.0
	for entry in scene.run_state.get("journal", []).slice(-12):
		print("  J %s/%s: %s" % [entry.get("kind"), entry.get("category"), str(entry.get("reason", "")).left(140)])
	print("PROBE DONE")
	quit(0)
