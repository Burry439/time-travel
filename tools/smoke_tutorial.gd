extends SceneTree
## The tutorial, "The first morning" (GDD D-50). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_tutorial.gd  [-- --capture]
## The title's Tutorial button starts one; the device speaks; walking up the road and picking up two things moves
## the story on; asking the device answers (its written hint on stub); then, in a developer tutorial journey, the
## steps the stub judge can't do are skipped, Kade walks over and lends his staff, Pack & gear puts it in hand,
## the bout is fought, and the closing card appears.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("TUTORIAL SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


func find_button(node: Node, text: String) -> Button:
	for child in node.get_children():
		if child is Button and (child as Button).text == text:
			return child
		var found := find_button(child, text)
		if found:
			return found
	return null


func step_id() -> String:
	var tutorial = scene.run_state.get("tutorial")
	if typeof(tutorial) != TYPE_DICTIONARY or tutorial.get("done", false):
		return "done"
	return str(scene.ui.device.story.steps[int(tutorial.step)].id)


func wait_for_step(wanted: String, seconds := 20.0) -> bool:
	var waited := 0.0
	while step_id() != wanted and waited < seconds:
		await create_timer(0.25).timeout
		waited += 0.25
	return step_id() == wanted


func walk(cells: Array) -> bool:
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if not reply.ok:
			return false
		scene._accept_state(reply.data.state)
	var last: Array = cells[-1]
	scene.predicted_cell = Vector2i(last[0], last[1])
	scene.player.position = scene._cell_center(last[0], last[1])
	return true


func take(object_id: String) -> bool:
	var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": object_id, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("take")})
	if reply.ok:
		scene._accept_state(reply.data.state)
	return reply.ok


func skip() -> void:
	var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/tutorial/skip" % scene.run_state.run_id, {})
	if reply.ok:
		scene._accept_state(reply.data.state)


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	# The title's Tutorial button: a tutorial journey, and the device speaks.
	var start := find_button(scene.menu, "Tutorial (first time)")
	if not check(start != null, "No Tutorial button on the title"):
		return
	start.pressed.emit()
	for _i in 40:
		await create_timer(0.1).timeout
		if not scene.run_state.is_empty():
			break
	if not check(scene.run_state.get("scenario") == "tutorial" and step_id() == "awake", "The tutorial didn't start"):
		return
	await create_timer(1.5).timeout
	if not check(scene.ui.device.panel.visible and not str(scene.ui.device.words.text).is_empty(), "The device didn't speak"):
		return
	if not check(scene.ui.hud.goal.text == "Awake", "The objective panel doesn't show the step: " + scene.ui.hud.goal.text):
		return
	await screenshot("tutorial_awake")
	# Walk up the road to the verge: the clock beat moves the story on.
	if not check(await walk([[48, 67], [48, 66], [48, 65], [48, 64], [48, 63], [48, 62]]), "Could not walk up the road"):
		return
	if not check(await wait_for_step("hands"), "Reaching the verge didn't move the story on: " + step_id()):
		return
	if not check(await take("branch_a") and await take("flint_a"), "Could not pick things up"):
		return
	if not check(await wait_for_step("smithy"), "Carrying two things didn't move the story on: " + step_id()):
		return
	# Ask the device (H): on stub it answers with the step's written hint.
	scene.ui.device.open_ask()
	await scene.ui.device._ask("Where do I go?")
	var said: Array = scene.run_state.get("device_log", [])
	if not check(not said.is_empty() and str(said[-1].get("question", "")) == "Where do I go?", "Asking the device didn't answer"):
		return
	await screenshot("tutorial_device")
	# A developer tutorial journey for the rest: skip what the stub judge can't do.
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer", "scenario": "tutorial"})
	scene._enter_run(created.data, false)
	await process_frame
	for _i in 5: # awake, hands, smithy, remedy, treat
		await skip()
	if not check(step_id() == "arm", "Skipping didn't reach 'Arm yourself': " + step_id()):
		return
	# Kade walks over and lends his practice staff and shield.
	var lent := false
	for _i in 120:
		await create_timer(0.25).timeout
		if str(scene.run_state.objects.get("practice_staff", {}).get("holder_id", "")) == "player":
			lent = true
			break
	if not check(lent, "Kade never lent the practice staff"):
		return
	scene.ui.open_inventory()
	await process_frame
	var right := find_button(scene.ui.modal, "Right hand")
	if not check(right != null, "No 'Right hand' button in Pack & gear"):
		return
	right.pressed.emit()
	if not check(await wait_for_step("bout"), "Holding the staff didn't move the story on: " + step_id()):
		return
	scene.ui.close_modal_now()
	# The bout: Kade squares up (he's beside you), and it's fought to "enough" either way.
	var fought := false
	for _i in 120:
		await create_timer(0.25).timeout
		if scene.in_fight():
			fought = true
			var kade: Dictionary = scene.ui.npc_record("npc_kade_east")
			var toward := Vector2(float(kade.x), float(kade.y)) - Vector2(scene.run_state.player.x, scene.run_state.player.y)
			if toward.length() > 0.5:
				scene.facing_row = scene._facing_for(toward.normalized())
			await scene.fight.strike("right")
		elif fought or step_id() != "bout":
			break
	if not check(fought, "The bout never started"):
		return
	if not check(await wait_for_step("wonder"), "The bout's end didn't move the story on: " + step_id()):
		return
	await skip() # The demonstration (the stub judge can't show a real one).
	for _i in 20:
		await create_timer(0.2).timeout
		if scene.ui.modal_kind == "tutorial_end":
			break
	if not check(step_id() == "done" and scene.ui.modal_kind == "tutorial_end", "No closing card: " + step_id()):
		return
	await screenshot("tutorial_end")
	print("TUTORIAL SMOKE PASSED: %d device lines, bout: %s" % [scene.run_state.get("device_log", []).size(),
		str(scene.run_state.journal.filter(func(e) -> bool: return str(e.get("category", "")).begins_with("spar_")).map(
			func(e) -> String: return str(e.category)))])
	quit(0)
