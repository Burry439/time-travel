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


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--seconds="):
			seconds = float(arg.get_slice("=", 1))
	call_deferred("_run")


func _process(_delta: float) -> bool:
	var now := Time.get_ticks_usec()
	if last_usec > 0:
		frames.append((now - last_usec) / 1000.0)
	last_usec = now
	return false


func fail(reason: String) -> void:
	push_error("COMBAT PROFILE FAILED: " + reason)
	quit(1)


func _api(method: int, path: String, body := {}) -> Dictionary:
	var started := Time.get_ticks_usec()
	var reply: Dictionary = await scene._api(method, path, body)
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


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await _api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not created.ok:
		fail("Start the backend first")
		return
	scene._enter_run(created.data, false)
	await process_frame
	var took: Dictionary = await _api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": "stone_b", "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("take")})
	if took.ok:
		scene._accept_state(took.data.state)
		await scene.fight.equip("stone_b", "right")
	var started_at := Time.get_ticks_msec()
	var next_report := 5.0
	var round := 0
	while (Time.get_ticks_msec() - started_at) / 1000.0 < seconds:
		if not scene.run_state.player.get("alive", true):
			print("The stranger died; rewinding.")
			await scene.rewind()
			await create_timer(1.0).timeout
		if not scene.in_fight() and scene.run_state.player.get("alive", true):
			round += 1
			var who: Array = [["npc_hessa_marr", "npc_darin_ko", "npc_tomas_reed"], ["npc_mara_venn", "npc_jory_venn"]][round % 2]
			var fight: Dictionary = await _api(HTTPClient.METHOD_POST, "/runs/%s/dev/fight" % scene.run_state.run_id,
				{"npc_ids": who, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("fight")})
			if fight.ok:
				scene._accept_state(fight.data.state)
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
				scene.facing_row = scene._facing_for(toward.normalized())
		scene.fight.strike("right")
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
	quit(0)
