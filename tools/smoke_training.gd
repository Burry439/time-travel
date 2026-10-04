extends SceneTree
## Training (GDD D-59). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_training.gd  [-- --capture]
## The title's Training opens the catalogue (Basics first; the Developer tab, in a developer build, has the test
## room). Playing the test room to its end brings up the level complete screen: the time, what was practised, a
## rating that's saved, and the way back to Training, where the room is now marked done.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func shot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.5).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/%s.png" % name)


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("TRAINING SMOKE FAILED: " + reason)
		quit(1)
	return condition


func find_button(node: Node, text: String) -> Button:
	for child in node.get_children():
		if child is Button and (child as Button).text == text:
			return child
		var found := find_button(child, text)
		if found:
			return found
	return null


func has_text(node: Node, text: String) -> bool:
	for label in node.find_children("*", "Label", true, false):
		if text in (label as Label).text:
			return true
	return false


func wait_for(kind: String, button := "") -> bool:
	for _i in 60:
		await create_timer(0.1).timeout
		if scene.ui.modal_kind == kind and (button.is_empty() or find_button(scene.ui.modal, button) != null):
			return true
	return false


func wait_text(text: String) -> bool:
	for _i in 60:
		await create_timer(0.1).timeout
		if scene.ui.modal.visible and has_text(scene.ui.modal, text):
			return true
	return false


func read_cards() -> void:
	for _i in 30:
		await create_timer(0.15).timeout
		if scene.ui.guide.is_open():
			scene.ui.guide._next()
		elif not scene.ui.guide.sending:
			await create_timer(0.3).timeout
			if not scene.ui.guide.is_open():
				return


func post(path: String, body: Dictionary) -> bool:
	body.merge({"expected_version": scene.run_state.event_seq, "request_id": scene.request_id(path)})
	var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/%s" % [scene.run_state.run_id, path], body)
	if reply.ok:
		scene.accept_state(reply.data.state)
	return reply.ok


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	find_button(scene.menu, "Training").pressed.emit()
	if not check(await wait_for("training", "Play"), "The Training screen didn't open on Basics"):
		return
	if not check(has_text(scene.ui.modal, "A cup of water") and has_text(scene.ui.modal, "Next"),
			"Basics doesn't list its first level, suggested"):
		return
	await shot("training")
	find_button(scene.ui.modal, "Developer").pressed.emit()
	if not check(await wait_text("A test room"), "No test room for developers"):
		return
	var play := find_button(scene.ui.modal, "Play")
	play = play if play else find_button(scene.ui.modal, "Play again") # Done in an earlier run on this database.
	play.pressed.emit()
	for _i in 40:
		await create_timer(0.1).timeout
		if scene.run_state.get("scenario") == "test_room":
			break
	if not check(scene.map_id == "test_room", "The test room didn't start"):
		return
	await read_cards()
	var cells := []
	for i in 8:
		cells.append([9 - i, 11 - i] if i < 7 else [3, 4])
	if not check(await post("move", {"cells": cells}) and await post("explore", {"elapsed_ms": 500}),
			"Couldn't walk to the hearth"):
		return
	await read_cards()
	var hessa: Dictionary = scene.run_state.npcs.filter(func(n) -> bool: return n.id == "npc_hessa_marr")[0]
	var beside := []
	var at := Vector2i(3, 4)
	while at != Vector2i(int(hessa.x), int(hessa.y) + 1):
		at += Vector2i(signi(int(hessa.x) - at.x), signi(int(hessa.y) + 1 - at.y))
		beside.append([at.x, at.y])
	if not beside.is_empty():
		await post("move", {"cells": beside})
	if not check(await post("say", {"npc_id": "npc_hessa_marr", "text": "Good day to you."}), "Couldn't talk to Hessa"):
		return
	scene.ui.bar.close()
	await post("explore", {"elapsed_ms": 500})
	await read_cards()
	if not check(await wait_for("level_complete"), "No level complete screen: %s" % str(scene.run_state.tutorial)):
		return
	if not check(has_text(scene.ui.modal, "You took") and has_text(scene.ui.modal, "You practised"),
			"The level complete screen doesn't say how it went"):
		return
	await shot("level_complete")
	find_button(scene.ui.modal, "About right").pressed.emit()
	for _i in 30:
		await create_timer(0.1).timeout
		if has_text(scene.ui.modal, "Thank you"):
			break
	if not check(has_text(scene.ui.modal, "Thank you"), "The rating wasn't saved"):
		return
	find_button(scene.ui.modal, "Next").pressed.emit() # Next is the Training menu, never another journey.
	if not check(await wait_text("✓ Done"), "Back in Training, no done mark"):
		return
	print("TRAINING SMOKE PASS: the catalogue, a level to its end, its complete screen and rating, and the done mark")
	quit(0)
