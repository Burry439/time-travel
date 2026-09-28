extends SceneTree
## UI makeover smoke test (GDD D-34, D-35). Needs the backend running with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_ui.gd  [-- --capture]
## Hover and clicks, the inventory bar, the one text line, drag-to-write, head status, the journal
## and map, and UI scale. Creates a disposable developer run without replacing the last-run pointer.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("UI SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.3).timeout
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


func settle() -> bool:
	await process_frame
	for i in 200:
		if not scene.request_busy and not scene.ui.round_playing:
			return true
		await create_timer(0.1).timeout
	return false


func walk_to(x: int, y: int) -> bool:
	for attempt in 10:
		var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
		if here == Vector2i(x, y):
			break
		var cells := []
		while here != Vector2i(x, y) and cells.size() < 20:
			here += Vector2i(signi(x - here.x), signi(y - here.y))
			cells.append([here.x, here.y])
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
			scene._accept_state(reply.data.state)
		if not reply.ok:
			break
	scene.predicted_cell = Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	scene.player.position = scene._cell_center(scene.predicted_cell.x, scene.predicted_cell.y)
	scene.camera.reset_smoothing()
	return scene.predicted_cell == Vector2i(x, y)


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	scene.camera_zoom = 1.0
	await process_frame
	var ui: Control = scene.ui
	if not check(ui.hud.visible and ui.hud.inventory.visible and ui.hud.slots_box.get_child_count() == 10, "No inventory bar %s %s %s" % [ui.hud.visible, ui.hud.inventory.visible, ui.hud.slots_box.get_child_count()]):
		return
	# The start is at the south edge, where the camera can't follow: the view lifts past the edge so the
	# stranger stays clear of the pack, and of the dialogue bar when it's open.
	var screen_bottom: float = scene.get_viewport_rect().size.y
	await create_timer(1.0).timeout
	var feet: float = scene.player.get_global_transform_with_canvas().origin.y
	if not check(feet < screen_bottom - ui.bottom_cover(), "The pack covers the stranger: feet at %s, pack from %s" % [
			feet, screen_bottom - ui.bottom_cover()]):
		return
	await screenshot("ui-hud")
	ui.open_try()
	await create_timer(1.2).timeout
	feet = scene.player.get_global_transform_with_canvas().origin.y
	if not check(feet < screen_bottom - ui.bottom_cover(), "The dialogue bar covers the stranger: feet at %s, bar from %s" % [
			feet, screen_bottom - ui.bottom_cover()]):
		return
	await screenshot("ui-bar-south-edge")
	ui.bar.close()

	# Hover: what a click will do, and whether it's within reach.
	var branch: Dictionary = ui.cursor.describe("branch_a")
	if not check(branch.verb == "Pick up the fallen branch" and branch.cursor == "take" and branch.reachable, "Branch hover: " + str(branch)):
		return
	var sapling: Dictionary = ui.cursor.describe("sapling_a")
	if not check(str(sapling.verb).begins_with("Use the") and sapling.action == "use", "Sapling hover: " + str(sapling)):
		return
	var far: Dictionary = ui.cursor.describe("npc_roderic_vale")
	if not check(far.tone == "far" and not far.reachable and far.cursor == "far", "Far hover: " + str(far)):
		return
	# Picking by position: the branch's sprite is under its own centre.
	var picked: Dictionary = ui.cursor.pick(scene.get_node("M2Objects/branch_a").global_position)
	if not check(picked.get("id") == "branch_a", "Picking the branch by position: " + str(picked)):
		return

	# Left click on a loose thing picks it up (after walking there) and it shows in the pack.
	scene._left_click(branch)
	if not check(await settle() and scene.run_state.objects.branch_a.holder_id == "player"
			and "branch_a" in ui.hud.slot_ids(), "Click to pick up failed"):
		return
	await screenshot("ui-pack")

	# Drag from the pack writes the line: onto a person, onto another item.
	if not check(ui.drop_phrase("branch_a", {}) == "Put down the fallen branch", "Drop on ground phrase"):
		return
	ui.drop_on_item("branch_a", "branch_a")
	scene.ui.bar.close()

	# The one text line alone: a deed becomes an inline result in the bar's log.
	ui.open_try()
	await process_frame
	await process_frame
	if not check(ui.bar.visible and ui.bar.who.text == "You" and not ui.hud.inventory.visible, "Bar did not open for you: %s %s %s" % [ui.bar.visible, ui.bar.who.text, ui.hud.inventory.visible]):
		return
	ui.bar.add_reference("cord_a")
	if not check("the short cord" in ui.bar.line.text and "cord_a" in ui.bar.selected, "Pointing did not reference the cord"):
		return
	ui.bar.line.text = "tie the short cord around the fallen branch"
	ui.bar.submit()
	if not check(await settle() and ui.bar.own_log[-1].kind == "result" and ui.bar.last_intent.kind == "do",
			"No inline result: " + str(ui.bar.own_log)):
		return
	await screenshot("ui-result-inline")
	# Speech with nobody near is answered honestly.
	ui.bar.line.text = "“Hello? Is anyone there?”"
	ui.bar.submit()
	if not check(await settle() and ui.bar.own_log[-1].kind == "note" and "Nobody" in str(ui.bar.own_log[-1].text)
			and ui.bar.line.text.begins_with("“Hello"), "Nobody-hears message missing"):
		return
	# A server error (plain-text 500) is reported honestly and leaves the line usable.
	var stumble: String = scene._reply_problem({"status": 500, "data": null})
	ui.bar.wait("test")
	ui.bar.problem(stumble)
	if not check("HTTP 500" in stumble and ui.bar.line.editable and not ui.bar.waiting, "A 500 left the bar stuck"):
		return
	ui.bar.line.text = ""
	ui.bar.escape()
	if not check(not ui.bar.visible, "Esc did not close the bar"):
		return

	# At the inn: Hessa's bucket is hers (a red "Steal"), and dragging onto her writes a gift.
	if not check(await walk_to(36, 54), "Could not walk to the inn"):
		return
	var bucket: Dictionary = ui.cursor.describe("bucket_hessa")
	if not check(bucket.verb == "Steal Hessa's wooden bucket" and bucket.tone == "steal" and bucket.cursor == "steal",
			"Steal hover: " + str(bucket)):
		return
	var hessa: Dictionary = ui.cursor.describe("npc_hessa_marr")
	if not check(hessa.verb == "Talk to Hessa" and hessa.cursor == "talk", "Talk hover: " + str(hessa)):
		return
	picked = ui.cursor.pick(scene.get_node("NPCs/npc_hessa_marr").position + Vector2(0, -50))
	if not check(picked.get("id") == "npc_hessa_marr", "Picking Hessa by her body: " + str(picked)):
		return
	var carried: Array = ui.hud.slot_ids()
	if not check(not carried.is_empty(), "Nothing carried to drag"):
		return
	var item: Dictionary = scene.run_state.objects[carried[0]]
	if not check(ui.drop_phrase(carried[0], hessa) == "Give the %s to Hessa" % item.name, "Drop on person phrase"):
		return
	ui._write_line("give the %s to Hessa" % item.name, "npc_hessa_marr", [carried[0]])
	if not check(ui.bar.visible and ui.bar.target == "npc_hessa_marr" and ui.bar.line.text.begins_with("give the")
			and carried[0] in ui.bar.selected, "Drag onto Hessa did not write the line"):
		return
	await screenshot("ui-drag-to-person")
	ui.bar.line.text = ""
	ui.bar.escape()

	# Right click: the inspect card.
	ui.card.show_for("bucket_hessa")
	if not check(ui.card.visible and ui.card.shown_id == "bucket_hessa", "Inspect card did not open"):
		return
	await screenshot("ui-inspect-card")
	ui.card.hide()

	# Head status: "…" while someone is thinking.
	scene.run_state["pending_minds"] = [{"npc_id": "npc_hessa_marr", "kind": "decide", "why": "test"}]
	var status: Node2D = scene.get_node("NPCs/npc_hessa_marr/Status")
	await process_frame
	await process_frame
	if not check("thinking" in status.signs, "No thinking sign: " + str(status.signs)):
		return
	scene.run_state["pending_minds"] = []
	scene.warm_until["npc_hessa_marr"] = Time.get_ticks_msec() / 1000.0 + 3.0
	await process_frame
	if not check("warm" in status.signs, "No warm sign"):
		return
	await screenshot("ui-head-status")

	# Journal: leads and the map (revealed where you walked).
	ui.open_journal("map")
	await process_frame
	if not check(ui.modal_kind == "journal" and ui.visited.has(Vector2i(12, 17)) and ui.visited.has(Vector2i(9, 13)),
			"Journal map or visited places missing: " + str(ui.visited.keys().slice(0, 6))):
		return
	await screenshot("ui-journal-map")
	ui.close_modal()
	ui.open_menu("settings")
	ui.ui_scale = 1.2
	ui.apply_scale()
	if not check(is_equal_approx(ui.root.scale.x, 1.2) and ui.root.size.x < 1100, "UI scale did not apply"):
		return
	ui.ui_scale = 1.0
	ui.apply_scale()
	ui.close_modal()
	print("UI SMOKE PASSED")
	quit(0)
