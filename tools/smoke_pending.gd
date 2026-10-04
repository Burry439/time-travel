extends SceneTree
## Pending intention: Escape frees movement; the server receives that movement while the intent remains pending.

func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var scene: Node2D = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "normal"})
	if not created.ok:
		push_error("PENDING SMOKE FAILED: backend unavailable")
		quit(1)
		return
	scene.enter_run(created.data, false)
	var first_y := int(scene.run_state.player.y)
	scene.request_busy = true
	scene.intent_pending = true
	scene.ui.bar.wait("Considering a physical intention")
	scene.ui.bar.escape()
	Input.action_press("move_up")
	for frame in 60:
		await physics_frame
	Input.action_release("move_up")
	while scene.movement_sync_active:
		await process_frame
	var fresh: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, scene.run_path())
	if not fresh.ok or int(fresh.data.player.y) >= first_y or scene.sync_error or scene.ui.bar.visible:
		push_error("PENDING SMOKE FAILED: movement or dismissal blocked during pending intention")
		quit(1)
		return
	scene.intent_pending = false
	scene.request_busy = false
	print("PENDING SMOKE PASSED: movement reached the server with the intention still pending")
	quit(0)
