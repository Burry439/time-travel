extends SceneTree
## Combat soak test: a long real-time fight in the real scene, watching for slowdown and leaks.
## Needs the backend (stub is enough):
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot_v4.7.2-stable_win64_console.exe --path . --script res://tools/profile_combat.gd  [-- --seconds=90]
## Every 5 s it prints frame times, node and object counts, memory, and the slowest request, while three people
## keep coming at the stranger and the stranger keeps swinging (with a stone, then fists, then at thin air).
var scene: Node2D
var seconds := 90.0
var frames: Array = []
var last_usec := 0
var worst_request_ms := 0.0
var fixture_run := ""
var baseline_nodes := 0
var baseline_orphans := 0
var max_nodes := 0
var max_orphans := 0
var worst_input_ms := 0.0


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--seconds="):
			seconds = float(arg.get_slice("=", 1))
		if arg.begins_with("--run="):
			fixture_run = arg.get_slice("=", 1)
	call_deferred("_run")


func _process(_delta: float) -> bool:
	var now := Time.get_ticks_usec()
	if last_usec > 0:
		frames.append((now - last_usec) / 1000.0)
	last_usec = now
	max_nodes = maxi(max_nodes, int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)))
	max_orphans = maxi(max_orphans, int(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT)))
	return false


func fail(reason: String) -> void:
	push_error("COMBAT PROFILE FAILED: " + reason)
	quit(1)


func _api(method: int, path: String, body := {}) -> Dictionary:
	var started := Time.get_ticks_usec()
	var reply: Dictionary = await scene.net.api(method, path, body)
	worst_request_ms = maxf(worst_request_ms, (Time.get_ticks_usec() - started) / 1000.0)
	return reply


func _report(label: String) -> void:
	var times := frames.duplicate()
	frames.clear()
	times.sort()
	if times.is_empty():
		return
	var pick := func(q: float) -> float: return times[mini(times.size() - 1, int(times.size() * q))]
	print(("%-10s frames %4d  p50 %5.1f  p95 %6.1f  max %7.1f ms | nodes %5d  objects %6d  orphans %4d | "
		+ "mem %6.1f MB | worst request %6.0f ms | health %d  fight %s  journal %d") % [
		label, times.size(), pick.call(0.5), pick.call(0.95), times[-1],
		Performance.get_monitor(Performance.OBJECT_NODE_COUNT), Performance.get_monitor(Performance.OBJECT_COUNT),
		Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0, worst_request_ms,
		int(scene.run_state.player.get("health", 0)), "yes" if scene.in_fight() else "no",
		scene.run_state.get("journal", []).size()])
	worst_request_ms = 0.0
	for key in ["state world", "state fight", "state panels", "parse explore", "animate_npcs"]:
		var measure: Array = scene.prof.get(key, [0, 0, 0])
		if int(measure[0]) > 0:
			print("  %s avg %.3f ms (%d calls)" % [key, float(measure[1]) / float(measure[0]) / 1000.0, int(measure[0])])


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await _api(HTTPClient.METHOD_GET, "/runs/" + fixture_run) if not fixture_run.is_empty() else \
		await _api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not created.ok:
		fail("Start the backend first")
		return
	scene.enter_run(created.data, false)
	if not fixture_run.is_empty():
		scene.thinking_lanes.react = true # Hold the fixture's chosen motives constant during the rendered soak.
		scene.thinking_lanes.village = true
	await process_frame
	await create_timer(3.0).timeout # Cached map/cast art, shader and geometry warm-up are outside the measurement.
	baseline_nodes = int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	baseline_orphans = int(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
	max_nodes = baseline_nodes
	max_orphans = baseline_orphans
	frames.clear()
	var took: Dictionary = await _api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": "stone_b", "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("take")})
	if took.ok:
		scene.accept_state(took.data.state)
		await scene.fight.equip("stone_b", "right")
	var started_at := Time.get_ticks_msec()
	frames.clear()
	last_usec = 0
	worst_request_ms = 0.0
	var next_report := 5.0
	var round := 0
	while (Time.get_ticks_msec() - started_at) / 1000.0 < seconds:
		if not scene.run_state.player.get("alive", true):
			print("The stranger died; rewinding.")
			await scene.rewind()
			await create_timer(1.0).timeout
		if fixture_run.is_empty() and not scene.in_fight() and scene.run_state.player.get("alive", true):
			round += 1
			var who: Array = [["npc_hessa_marr", "npc_darin_ko", "npc_tomas_reed"], ["npc_mara_venn", "npc_jory_venn"]][round % 2]
			var fight: Dictionary = await _api(HTTPClient.METHOD_POST, "/runs/%s/dev/fight" % scene.run_state.run_id,
				{"npc_ids": who, "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("fight")})
			if fight.ok:
				scene.accept_state(fight.data.state)
			else:
				print("dev fight refused: ", str(fight.get("data")).left(200))
		# Swing at whoever is closest (Space), else at thin air.
		var nearest: Node2D = null
		for npc in scene.run_state.get("npcs", []):
			var actor := scene.get_node_or_null("NPCs/" + str(npc.id)) as Node2D
			if actor and npc.get("alive", true) and not npc.get("down", false) and \
					(nearest == null or actor.position.distance_to(scene.player.position) < nearest.position.distance_to(scene.player.position)):
				nearest = actor
		if nearest:
			var toward: Vector2 = nearest.position - scene.player.position
			if toward.length() > 1.0:
				scene.facing_row = scene.facing_for(toward.normalized())
		var input_at := Time.get_ticks_usec()
		scene.fight.strike("right")
		if scene.player_visual.attacks.has("right") and str(scene.player_visual.attacks.right.key).begins_with("predicted:"):
			worst_input_ms = maxf(worst_input_ms, float(Time.get_ticks_usec() - input_at) / 1000.0)
		await create_timer(0.4).timeout
		var elapsed := (Time.get_ticks_msec() - started_at) / 1000.0
		if elapsed >= next_report:
			_report("t=%ds" % int(elapsed))
			next_report += 5.0
	for entry in scene.run_state.get("journal", []).slice(-25):
		print("  J %s/%s: %s" % [entry.get("kind"), entry.get("category"), str(entry.get("reason", "")).left(150)])
	for npc in scene.run_state.get("npcs", []):
		print("  %s health %s down %s alive %s job %s" % [npc.name, npc.get("health"), npc.get("down"), npc.get("alive"),
			str(npc.get("mind", {}).get("job", {}))])
	print("COMBAT PROFILE DONE")
	print("PROFILE GROWTH: baseline nodes %d, peak %d; baseline orphans %d, peak %d; anticipation worst %.3f ms"
		% [baseline_nodes, max_nodes, baseline_orphans, max_orphans, worst_input_ms])
	var final_nodes := int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT))
	print("PROFILE FINAL: nodes %d; transient peak above baseline %d" % [final_nodes, max_nodes - baseline_nodes])
	# Requests, hit effects and bubbles are temporary nodes; reject continuing growth, not their bounded peak.
	if max_orphans > baseline_orphans or final_nodes > baseline_nodes + 16 or max_nodes > baseline_nodes + 64:
		fail("continuing node/orphan growth")
		return
	quit(0)
