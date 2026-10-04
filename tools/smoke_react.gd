extends SceneTree
## The moment itself (GDD D-39). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_react.gd  [-- --capture]
## Take Hessa's bowl: she perceives the actual incident, and her individual reaction (the reaction lane)
## still arrives while the dialogue bar is open.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("REACT SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.3).timeout
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	await process_frame
	var cells := []
	for y in range(67, 54, -1):
		cells.append([48, y])
	for x in range(47, 38, -1):
		cells.append([x, 55])
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("move")})
		if not check(reply.ok, "Could not walk to the inn"):
			return
		scene.accept_state(reply.data.state)
	scene.predicted_cell = Vector2i(39, 55)
	scene.player.position = scene.cell_center(39, 55)
	scene.camera.reset_smoothing()
	var started := Time.get_ticks_msec()
	await scene.actions.quick_action("take", "bowl_hessa")
	await process_frame
	var hessa: Dictionary = scene.ui.npc_record("npc_hessa_marr")
	if not check(hessa.get("mind", {}).get("memories", []).any(
			func(m: Dictionary) -> bool: return m.kind == "theft" and m.get("object_id") == "bowl_hessa"),
			"Hessa did not perceive the actual stolen bowl"):
		return
	print("Theft perceived after ", Time.get_ticks_msec() - started, " ms")
	await screenshot("react-bowl")
	# Her considered reaction (the reaction lane) arrives even with the dialogue bar open.
	scene.ui.open_try()
	for i in 100:
		if not scene.run_state.pending_minds.any(func(p: Dictionary) -> bool: return p.kind == "decide"):
			break
		await create_timer(0.1).timeout
	if not check(not scene.run_state.pending_minds.any(func(p: Dictionary) -> bool: return p.kind == "decide"),
			"The reaction lane stalled while the dialogue bar was open"):
		return
	print("REACT SMOKE PASSED: reaction decided in ", Time.get_ticks_msec() - started, " ms with the bar open")
	quit(0)
