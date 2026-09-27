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
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
			scene._accept_state(reply.data.state)
		if not reply.ok:
			break
	scene.predicted_cell = Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
	scene.player.position = scene._cell_center(scene.predicted_cell.x, scene.predicted_cell.y)
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
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and int(health.data.seed_version) >= 5, "Backend missing or outdated; restart it"):
		return
	if not check(str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await process_frame
	if not check(await walk_to(36, 53), "Could not walk to the inn yard"):
		return

	# E on a living person opens the encounter panel.
	scene.nearby_target = "npc_hessa_marr"
	scene._interact()
	await process_frame
	if not check(scene.ui.modal_kind == "encounter" and scene.ui.talk_npc == "npc_hessa_marr", "Panel did not open"):
		return
	scene.ui.talk_input.text = "Good day. Is this your inn?"
	scene.ui._submit_talk()
	await process_frame
	if not check(scene.ui.talk_waiting, "No thinking indicator while waiting"):
		return
	await settle()
	var hessa: Dictionary = scene.ui.npc_record("npc_hessa_marr")
	var turns: Array = hessa.get("mind", {}).get("talk", [])
	if not check(turns.size() == 2 and turns[0].text == "Good day. Is this your inn?", "Exchange not recorded: " + str(turns)):
		return
	if not check(scene.ui.modal_kind == "encounter" and not scene.ui.talk_waiting and scene.ui.talk_input.editable
			and scene.in_encounter(), "Panel did not come back ready for the next line"):
		return
	if not check(scene.run_state.journal[-1].kind == "talk" or scene.run_state.journal.any(
			func(e: Dictionary) -> bool: return e.get("kind") == "talk"), "No journal entry for the exchange"):
		return
	if not check(typeof(scene.last_trace) == TYPE_DICTIONARY and scene.last_trace.kind == "talk", "No developer trace"):
		return
	var bubble := scene.get_node_or_null("NPCs/npc_hessa_marr/Speech") as Label
	if not check(bubble != null and bubble.text == str(turns[1].text), "No speech bubble for the reply"):
		return
	await screenshot("encounter-talk")

	# Closing the panel face to face is walking away: the encounter ends, then the panel closes.
	scene.ui.close_modal()
	if not check(await settle() and not scene.in_encounter() and scene.ui.encounter_over, "Walking away did not end it"):
		return
	scene.ui.close_modal()
	scene.ui.inspect("npc_hessa_marr")
	if not check(scene.ui.modal_kind == "person", "Inspect did not open"):
		return
	scene.ui.close_modal()
	scene.ui.open_journal()
	scene.ui.close_modal()

	# At the gate a guard walks up and stops you: their conversation opens with the halt.
	created = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await process_frame
	if not check(await walk_to(48, 16), "Could not walk up to the gate"):
		return
	for i in 300:
		if scene.ui.modal_kind == "encounter":
			break
		await create_timer(0.1).timeout
	if not check(scene.ui.modal_kind == "encounter" and scene.run_state.encounter.reason == "halt",
			"No guard stopped the stranger at the gate"):
		return
	var opening: Array = scene.run_state.encounter.log
	if not check(not opening.is_empty() and str(opening[0].text).contains("“"), "The halt line is not in the log"):
		return
	# A round where you act (the stub judge rules on it) while the guard, listening, answers what happened.
	scene.ui.talk_input.text = "hand the guard a stone"
	scene.ui._submit_do()
	if not check(await settle() and scene.run_state.encounter.round == 2, "The Do round did not resolve"):
		return
	var kinds: Array = scene.run_state.last_round.entries.map(func(e: Dictionary) -> String: return str(e.kind))
	if not check("do" in kinds, "The round has no action of yours: " + str(kinds)):
		return
	scene.ui._submit_simple("wait")
	if not check(await settle() and scene.run_state.encounter.round == 3, "The Wait round did not resolve"):
		return
	await screenshot("encounter-halt")
	# Yielding to a guard: arrested, marched down the south road, barred from the gate for a while.
	scene.ui._submit_simple("yield")
	if not check(await settle() and not scene.in_encounter() and scene.run_state.last_round.get("arrested", false),
			"Yielding to the guard did not end in an arrest"):
		return
	for i in 60:
		if not scene.request_busy:
			break
		await create_timer(0.1).timeout
	if not check(scene.predicted_cell == Vector2i(48, 66) and scene.ui.modal_kind == "", "Not marched to the south road"):
		return
	await screenshot("encounter-arrested")

	# Admission is decided on the server (see backend/tests/test_gate.py); the panel explains the route.
	scene.run_state["admitted"] = {"by": "npc_roderic_vale", "because": ["Hessa vouched for the stranger."]}
	scene._show_victory()
	if not check(scene.victory_panel.visible and "Hessa vouched" in scene.victory_route.text, "Victory route missing"):
		return
	print("TALK SMOKE PASSED")
	quit(0)
