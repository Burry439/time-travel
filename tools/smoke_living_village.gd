extends SceneTree

func _initialize() -> void:
	call_deferred("_run")


func _fail(reason: String) -> void:
	push_error(reason)
	quit(1)


func _run() -> void:
	var scene: Node2D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "normal"})
	if not created.ok or int(created.data.seed_version) < 3:
		_fail("Living-village backend unavailable")
		return
	scene._enter_run(created.data, false)
	if scene.get_node("NPCs").get_child_count() != 10:
		_fail("The living village did not spawn its full cast")
		return
	for npc in created.data.npcs:
		var rig := scene.get_node("NPCs/" + str(npc.id) + "/PaintedActor")
		if rig.actor_id != str(npc.name).to_lower() or rig.views.size() != 4:
			_fail("Missing unique four-view painted rig for " + str(npc.name))
			return
	var initial_guards := {}
	for npc in created.data.npcs:
		if str(npc.name) in ["Bren", "Oren", "Elin", "Kade"]:
			initial_guards[str(npc.id)] = Vector2(int(npc.x), int(npc.y))
	var walking_seen := false
	var working_seen := false
	for frame in 420:
		await physics_frame
		for npc in scene.run_state.npcs:
			var art := scene.get_node("NPCs/" + str(npc.id) + "/PaintedActor")
			if art.locomotion == "walk" and str(npc.name) in ["Bren", "Oren", "Elin", "Kade"]:
				walking_seen = true
			if art.locomotion == "work":
				working_seen = true
	scene.gameplay_active = false
	while scene.movement_sync_active:
		await process_frame
	var changed_guard := false
	for npc in scene.run_state.npcs:
		if initial_guards.has(str(npc.id)) and Vector2(int(npc.x), int(npc.y)) != initial_guards[str(npc.id)]:
			changed_guard = true
	if not walking_seen or not working_seen or not changed_guard or int(scene.run_state.sim_time_ms) < 5000:
		_fail("NPC clock or patrol animation did not advance")
		return
	scene.ui.open_pause()
	var paused_time := int(scene.run_state.sim_time_ms)
	var paused_guard: Vector2 = scene.get_node("NPCs/npc_elin_west").position
	await create_timer(1.2).timeout
	if int(scene.run_state.sim_time_ms) != paused_time or scene.get_node("NPCs/npc_elin_west").position != paused_guard:
		_fail("NPCs or clock moved while paused")
		return
	scene.ui.close_modal()
	scene.gameplay_active = true
	await create_timer(0.8).timeout
	scene.gameplay_active = false
	while scene.movement_sync_active:
		await process_frame
	if int(scene.run_state.sim_time_ms) <= paused_time:
		_fail("Village clock did not resume")
		return
	var saved: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/runs/" + str(scene.run_state.run_id))
	if not saved.ok or saved.data.npcs != scene.run_state.npcs:
		_fail("NPC state did not survive reload")
		return
	if DisplayServer.get_name() != "headless" and "--capture" in OS.get_cmdline_user_args():
		scene.player.position = Vector2(1552, 650)
		scene.camera.reset_smoothing()
		await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://docs/screenshots/living-gate-patrol.png")
		scene.player.position = Vector2(1450, 1690)
		scene.camera.reset_smoothing()
		await process_frame
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://docs/screenshots/living-inn-yard.png")
	print("LIVING VILLAGE PASS: guards patrolled, work animated, pause froze, reload restored")
	quit(0)
