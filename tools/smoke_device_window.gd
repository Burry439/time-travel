extends SceneTree
## The device as a companion (GDD D-55). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --path . --script res://tools/smoke_device_window.gd  [-- --capture]
## In the main game the device widget is always there. H opens the Device window; a quick question gets an answer
## (its written stand-in on stub) and both appear in the history; closed and opened again, the whole history is
## still there, and after a reload too.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("DEVICE WINDOW SMOKE FAILED: " + reason)
		quit(1)
	return condition


func press(keycode: Key) -> void:
	var key := InputEventKey.new()
	key.keycode = keycode
	key.pressed = true
	Input.parse_input_event(key)
	await process_frame
	var up := InputEventKey.new()
	up.keycode = keycode
	up.pressed = false
	Input.parse_input_event(up)
	await process_frame


func bubbles() -> int:
	return scene.ui.device.history_box.get_child_count() if is_instance_valid(scene.ui.device.history_box) else 0


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not check(created.ok, "Start the backend with AI_MODE=stub first"):
		return
	scene.enter_run(created.data, false)
	await create_timer(0.8).timeout
	if not check(scene.ui.device.panel.visible, "The device widget isn't there in the main game"):
		return
	await press(KEY_H)
	if not check(scene.ui.modal_kind == "device", "H didn't open the Device window"):
		return
	var empty := bubbles()
	await scene.ui.device._ask("What should I do next?")
	await process_frame
	var log: Array = scene.run_state.get("device_log", [])
	if not check(log.size() == 1 and str(log[0].get("question", "")) == "What should I do next?", "The question wasn't kept"):
		return
	if not check(bubbles() == 2 and empty <= 1, "The history doesn't show the question and the answer: %d" % bubbles()):
		return
	await scene.ui.device._ask("And the controls?")
	if capture:
		await create_timer(0.4).timeout
		await RenderingServer.frame_post_draw
		root.get_texture().get_image().save_png("res://docs/screenshots/device_window.png")
	scene.ui.close_modal_now()
	scene.ui.device.open_ask()
	await process_frame
	if not check(bubbles() == 4, "Reopened, the whole history isn't there: %d" % bubbles()):
		return
	var reloaded: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/runs/" + str(scene.run_state.run_id))
	if not check(reloaded.ok and reloaded.data.get("device_log", []).size() == 2, "The history didn't survive a reload"):
		return
	print("DEVICE WINDOW SMOKE PASSED")
	quit(0)
