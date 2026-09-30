extends SceneTree
var scene: Node2D
var capture := false

func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")

func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error(reason)
		quit(1)
	return condition

func screenshot(name: String) -> void:
	if not capture:
		return
	await process_frame
	await RenderingServer.frame_post_draw
	var picture := root.get_texture().get_image()
	var result := picture.save_png("res://docs/screenshots/" + name + ".png")
	check(result == OK, "Screenshot failed: " + name)

func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	await screenshot("feel-title")
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "normal"})
	if not check(created.ok, "Backend unavailable"):
		return
	if not check(int(created.data.geometry_version) == 3, "Restart the backend: map geometry is outdated"):
		return
	scene._enter_run(created.data, false)
	for direction in [Vector2.DOWN, Vector2.LEFT, Vector2.UP, Vector2.RIGHT,
		Vector2(1, 1).normalized(), Vector2(-1, 1).normalized(),
		Vector2(-1, -1).normalized(), Vector2(1, -1).normalized()]:
		var view: int = scene._facing_for(direction)
		scene.player_visual.set_motion(view, "walk", 12.0, 0.1)
		if not check(scene.player_visual.views[view].visible, "Missing painted view " + str(view)):
			return
	# Compare art at the stated default even if the player's saved zoom differs.
	scene.camera_zoom = 1.0
	await create_timer(0.25).timeout
	await screenshot("feel-south-road")
	await scene._quick_action("take", "branch_a")
	if not check(scene.run_state.objects.branch_a.holder_id == "player", "Quick pickup failed"):
		return
	if not check(not scene.get_node("M2Objects/branch_a").visible, "Picked-up object stayed on ground"):
		return
	scene.ui.open_inventory()
	await process_frame
	if not check(scene.ui.modal.visible and scene.ui.modal_kind == "inventory", "Inventory did not open"):
		return
	var view := Rect2(Vector2.ZERO, root.get_visible_rect().size)
	if not check(view.encloses(scene.ui.modal.get_global_rect()), "Inventory is outside the viewport"):
		return
	await screenshot("feel-inventory")
	await scene._quick_action("drop", "branch_a")
	if not check(scene.run_state.objects.branch_a.holder_id == null, "Drop failed"):
		return
	scene.ui.close_modal()
	var before: Vector2 = scene.player.position
	Input.action_press("move_up")
	Input.action_press("move_right")
	Input.action_press("run")
	await create_timer(0.25).timeout
	await screenshot("painted-diagonal-run")
	await create_timer(0.25).timeout
	if not check(scene.facing_row == 7 and scene.player_visual.views[7].visible, "Up-right diagonal did not use its painted view"):
		return
	Input.action_release("move_up")
	Input.action_release("move_right")
	Input.action_release("run")
	await create_timer(0.2).timeout
	var travelled: Vector2 = scene.player.position - before
	if not check(travelled.x > 75 and travelled.y < -75 and travelled.length() < 230,
			"Diagonal running failed or is too fast: " + str(travelled)):
		return
	while scene.movement_sync_active:
		await process_frame
	if not check(scene.move_queue.is_empty() and not scene.sync_error, "Movement did not sync"):
		return
	scene.ui.open_pause()
	before = scene.player.position
	Input.action_press("move_left")
	await create_timer(0.15).timeout
	Input.action_release("move_left")
	if not check(scene.player.position == before, "Player moved while paused"):
		return
	scene.ui.close_modal()
	var restored: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/runs/" + str(scene.run_state.run_id))
	if not check(restored.ok and restored.data.objects.branch_a.holder_id == null
			and restored.data.player == scene.run_state.player, "Reload lost movement or item state"):
		return
	var query := PhysicsPointQueryParameters2D.new()
	query.position = Vector2(1104, 1500)
	if not check(not scene.get_world_2d().direct_space_state.intersect_point(query).is_empty(), "Inn has no physical footprint"):
		return
	# Screenshot-only camera locations; never sent to the backend or saved.
	scene.gameplay_active = false
	scene.player.position = Vector2(1360, 1690)
	scene.camera.offset = Vector2.ZERO
	scene.camera.reset_smoothing()
	await create_timer(0.15).timeout
	await screenshot("feel-inn")
	scene.player.position = Vector2(1552, 510)
	scene.camera.reset_smoothing()
	await create_timer(0.15).timeout
	await screenshot("feel-gate")
	print("FEEL PASS: pickup, inventory, drop, diagonal run, pause, save/reload, and building collision passed")
	quit(0)
