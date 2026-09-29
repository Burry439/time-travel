extends SceneTree
## Gear and the stranger's hands (GDD D-49). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_gear.gd  [-- --capture]
## Pick up the fallen branch, put it in the right hand from the Pack & gear screen (it's drawn in the hand),
## swing it at Hessa (the wind-up plays, then the blow lands on the clock), swap hands with X, and check a worn
## sheet slices into four views on the rig.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("GEAR SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.3).timeout
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
	if not check(scene.fight.in_hand(scene.run_state.player, "body").get("id") == "clothes_player",
			"The stranger doesn't start in their own clothes"):
		return
	var took: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": "branch_a", "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("take")})
	if not check(took.ok, "Could not pick up the branch"):
		return
	scene._accept_state(took.data.state)
	# The Pack & gear screen: the branch, with a Right hand button.
	scene.ui.open_inventory()
	await process_frame
	if not check(scene.ui.modal_kind == "inventory", "Pack & gear didn't open"):
		return
	var right := find_button(scene.ui.modal, "Right hand")
	if not check(right != null, "No 'Right hand' button for the branch"):
		return
	await screenshot("gear_pack")
	right.pressed.emit()
	for _i in 40:
		await create_timer(0.1).timeout
		if scene.fight.in_hand(scene.run_state.player, "right").get("id") == "branch_a":
			break
	if not check(scene.fight.in_hand(scene.run_state.player, "right").get("id") == "branch_a", "The branch isn't in hand"):
		return
	scene.ui.close_modal_now()
	await process_frame
	var actor = scene.player_visual
	if not check(actor.held.has("right") and actor.held.right.texture != null, "The branch isn't drawn in the hand"):
		return
	# Walk to the inn (the road, then west), and Hessa comes at the stranger.
	var cells := []
	var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	while here.x != 48:
		here.x += signi(48 - here.x)
		cells.append([here.x, here.y])
	for y in (range(here.y - 1, 54, -1) if here.y > 55 else range(here.y + 1, 56)):
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
	var started: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/dev/fight" % scene.run_state.run_id,
		{"npc_ids": ["npc_hessa_marr"], "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("fight")})
	if not check(started.ok, "Could not start a fight"):
		return
	scene._accept_state(started.data.state)
	for _i in 60: # She runs in.
		await create_timer(0.2).timeout
		var her: Dictionary = scene.ui.npc_record("npc_hessa_marr")
		if Vector2(float(her.x), float(her.y)).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y)) <= 2.0:
			break
	var her_now: Dictionary = scene.ui.npc_record("npc_hessa_marr")
	var toward := Vector2(float(her_now.x), float(her_now.y)) - Vector2(scene.run_state.player.x, scene.run_state.player.y)
	scene.facing_row = scene._facing_for(toward.normalized())
	var before := float(her_now.get("health", 100))
	await scene.fight.strike("right")
	if not check(not actor.attack.is_empty() and str(actor.attack.animation) in ["overhead", "two_hand_swing"],
			"No wind-up played for the branch: " + str(actor.attack)):
		return
	await screenshot("gear_windup")
	for _i in 30:
		await create_timer(0.2).timeout
		if float(scene.ui.npc_record("npc_hessa_marr").get("health", 100)) < before:
			break
	if not check(float(scene.ui.npc_record("npc_hessa_marr").get("health", 100)) < before, "The blow never landed"):
		return
	# X: both hands are on the staff, so there's nothing to swap.
	await scene.fight.swap()
	if not check(scene.fight.in_hand(scene.run_state.player, "right").get("id") == "branch_a", "X moved a two-handed staff"):
		return
	# A worn sheet slices into four views (front, right, back, left) and sits on the rig.
	var sheet := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	sheet.fill_rect(Rect2i(8, 8, 16, 16), Color.RED)
	sheet.fill_rect(Rect2i(40, 8, 16, 16), Color.GREEN)
	sheet.fill_rect(Rect2i(8, 40, 16, 16), Color.BLUE)
	sheet.fill_rect(Rect2i(40, 40, 16, 16), Color.YELLOW)
	actor.set_gear(actor.held, {"body": sheet})
	var quads: Array = actor.worn.get("body", [])
	if not check(quads.size() == 4 and quads.all(func(q) -> bool: return q != null and q.get_size() == Vector2(16, 16)),
			"The worn sheet didn't slice into four views"):
		return
	print("GEAR SMOKE PASSED: branch in both hands (%s), Hessa hit, X refused, sheet sliced" % actor.held.get("right", {}).get("animation", "?"))
	quit(0)
