extends SceneTree
## Conversation and encounter smoke test. Needs the backend running with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_talk.gd  [-- --capture]
## Creates a disposable developer run without replacing the player's last-run pointer.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("TALK SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await process_frame
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png") == OK, "Screenshot failed")


## Walk the committed player along a straight line of cells (the server checks every step).
func walk_to(x: int, y: int) -> bool:
	for attempt in 10:
		var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
		if here == Vector2i(x, y):
			break
		var cells := []
		while here != Vector2i(x, y) and cells.size() < 20:
			here += Vector2i(signi(x - here.x), signi(y - here.y))
			cells.append([here.x, here.y])
		var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells, "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("move")})
		if typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
			scene.accept_state(reply.data.state)
		if not reply.ok:
			print("walk refused: ", reply.status, " ", JSON.stringify(reply.data).left(300))
			break
	scene.predicted_cell = Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	scene.player.position = scene.cell_center(scene.predicted_cell.x, scene.predicted_cell.y)
	return scene.predicted_cell == Vector2i(x, y)


## Wait for the request in flight (a round) to finish.
func settle() -> bool:
	await process_frame
	for i in 200:
		if not scene.request_busy and not scene.ui.round_playing:
			return true
		await create_timer(0.1).timeout
	return false


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and int(health.data.seed_version) >= 5, "Backend missing or outdated; restart it"):
		return
	if not check(str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	await process_frame
	if not check(await walk_to(36, 53), "Could not walk to the inn yard"):
		return

	# A left click on a living person opens the dialogue bar with them.
	scene.controls.left_click(scene.ui.cursor.describe("npc_hessa_marr"))
	await process_frame
	if not check(scene.ui.bar.visible and scene.ui.bar.target == "npc_hessa_marr", "Dialogue bar did not open"):
		return
	scene.ui.bar.line.text = "“Good day. Is this your inn?”"
	scene.ui.bar.submit()
	await process_frame
	if not check(scene.ui.bar.waiting, "No thinking indicator while waiting"):
		return
	await settle()
	var hessa: Dictionary = scene.ui.npc_record("npc_hessa_marr")
	var turns: Array = hessa.get("mind", {}).get("talk", [])
	if not check(turns.size() == 2 and turns[0].text == "Good day. Is this your inn?", "Exchange not recorded: " + str(turns)):
		return
	if not check(scene.ui.bar.showing_encounter() and not scene.ui.bar.waiting and scene.ui.bar.line.editable
			and scene.in_encounter(), "Bar did not come back ready for the next line"):
		return
	if not check(scene.run_state.journal[-1].kind == "talk" or scene.run_state.journal.any(
			func(e: Dictionary) -> bool: return e.get("kind") == "talk"), "No journal entry for the exchange"):
		return
	if not check(typeof(scene.last_trace) == TYPE_DICTIONARY and scene.last_trace.kind == "talk", "No developer trace"):
		return
	var bubble := scene.get_node_or_null("NPCs/npc_hessa_marr/Speech/Words") as Label
	if not check(bubble != null and str(turns[1].text).begins_with(bubble.text.trim_suffix("…")), "No speech bubble for the reply"):
		return
	await screenshot("encounter-talk")

	# Esc face to face is walking away: the encounter ends, then Esc closes the bar.
	scene.ui.bar.escape()
	if not check(await settle() and not scene.in_encounter() and scene.ui.bar.encounter_over, "Walking away did not end it"):
		return
	scene.ui.bar.escape()
	if not check(not scene.ui.bar.visible, "The bar did not close"):
		return
	scene.ui.card.show_for("npc_hessa_marr")
	if not check(scene.ui.card.visible and scene.ui.card.shown_id == "npc_hessa_marr", "Inspect card did not open"):
		return
	scene.ui.card.hide()
	scene.ui.open_journal()
	scene.ui.close_modal()

	# At the gate a guard walks up and stops you: their conversation opens with the halt.
	created = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(created.data, false)
	await process_frame
	if not check(await walk_to(48, 16), "Could not walk up to the gate"):
		return
	for i in 300:
		if scene.ui.bar.showing_encounter():
			break
		await create_timer(0.1).timeout
	if not check(scene.ui.bar.showing_encounter() and scene.run_state.encounter.reason == "halt",
			"No guard stopped the stranger at the gate"):
		return
	var opening: Array = scene.run_state.encounter.log
	if not check(not opening.is_empty() and str(opening[0].text).contains("“"), "The halt line is not in the log"):
		return
	# A round where you act (the stub judge rules on it) while the guard, listening, answers what happened.
	scene.ui.bar.set_mode("do", true) # A deed (D-55: the player says which).
	scene.ui.bar.line.text = "hand the guard a stone"
	scene.ui.bar.submit()
	if not check(await settle() and scene.run_state.encounter.round == 2, "The Do round did not resolve"):
		return
	var kinds: Array = scene.run_state.last_round.entries.map(func(e: Dictionary) -> String: return str(e.kind))
	if not check("do" in kinds and scene.ui.bar.last_intent.get("kind") == "do", "The round has no action of yours: " + str(kinds)):
		return
	scene.ui.bar.line.text = "I wait"
	scene.ui.bar.submit()
	if not check(await settle() and scene.run_state.encounter.round == 3, "The Wait round did not resolve"):
		return
	await screenshot("encounter-halt")
	# Yielding to a guard: arrested, marched down the south road, barred from the gate for a while.
	scene.ui.bar.line.text = "I give up"
	scene.ui.bar.submit()
	if not check(await settle() and not scene.in_encounter() and scene.run_state.last_round.get("arrested", false),
			"Yielding to the guard did not end in an arrest"):
		return
	for i in 60:
		if not scene.request_busy:
			break
		await create_timer(0.1).timeout
	if not check(scene.predicted_cell == Vector2i(48, 66) and not scene.ui.bar.visible, "Not marched to the south road"):
		return
	await screenshot("encounter-arrested")

	# Admission is decided on the server (see backend/tests/test_gate.py); the panel explains the route.
	scene.run_state["admitted"] = {"by": "npc_roderic_vale", "because": ["Hessa vouched for the stranger."]}
	scene.show_victory()
	if not check(scene.victory_panel.visible and "Hessa vouched" in scene.victory_route.text, "Victory route missing"):
		return
	print("TALK SMOKE PASSED")
	quit(0)
