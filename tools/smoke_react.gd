extends SceneTree
## The moment itself (GDD D-39). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_react.gd  [-- --capture]
## Take Hessa's bowl: she shouts and shows "!" at once (code), and her considered reaction (Jev's lane)
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
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await process_frame
	var cells := []
	for y in range(67, 54, -1):
		cells.append([48, y])
	for x in range(47, 38, -1):
		cells.append([x, 55])
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if not check(reply.ok, "Could not walk to the inn"):
			return
		scene._accept_state(reply.data.state)
	scene.predicted_cell = Vector2i(39, 55)
	scene.player.position = scene._cell_center(39, 55)
	scene.camera.reset_smoothing()
	var started := Time.get_ticks_msec()
	await scene._quick_action("take", "bowl_hessa")
	await process_frame
	var bubble := scene.get_node_or_null("NPCs/npc_hessa_marr/Speech/Words") as Label
	if not check(bubble != null and ("bowl" in bubble.text or "mine" in bubble.text),
			"Hessa didn't shout at once: " + (bubble.text if bubble else "no bubble")):
		return
	var status: Node2D = scene.get_node("NPCs/npc_hessa_marr/Status")
	await process_frame
	if not check("alarmed" in status.signs, "No '!' over Hessa: " + str(status.signs)):
		return
	print("Bark after ", Time.get_ticks_msec() - started, " ms (including the walk there)")
	await screenshot("react-bowl")
	# Her considered reaction (Jev's lane) arrives even with the dialogue bar open.
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
