extends SceneTree

func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene: Node2D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "normal"})
	if not created.ok:
		push_error("Backend unavailable for responsiveness test")
		quit(1)
		return
	scene.enter_run(created.data, false)
	var beginning: Vector2 = scene.player.position
	var start_ms := Time.get_ticks_msec()
	var max_queue := 0
	var still_frames := 0
	var previous: Vector2 = scene.player.position
	Input.action_press("move_up")
	Input.action_press("run")
	for frame in 180:
		await physics_frame
		max_queue = maxi(max_queue, scene.move_queue.size())
		if frame > 5 and scene.player.position.distance_to(previous) < 0.1:
			still_frames += 1
		previous = scene.player.position
	Input.action_release("move_up")
	Input.action_release("run")
	var seconds := float(Time.get_ticks_msec() - start_ms) / 1000.0
	var speed := beginning.distance_to(scene.player.position) / seconds
	while scene.movement_sync_active:
		await process_frame
	if scene.sync_error or max_queue >= 16 or still_frames > 4 or speed < 320.0:
		push_error("Run stuttered: speed %.1f px/s, %s still frames, max queue %s, sync error %s" % [
			speed, still_frames, max_queue, scene.sync_error])
		quit(1)
		return
	print("RESPONSIVENESS PASS: %.1f px/s, %s still frames, max queued moves %s" % [speed, still_frames, max_queue])
	quit(0)
