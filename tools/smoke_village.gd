extends SceneTree
## The village's own life, seen from the client (GDD D-37). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_village.gd  [-- --capture]
## Stands near the gate guards while time passes: people plan their day in the thinking lane, two of
## them fall into talk, their bubbles show, and the inspect card says how they seem and what they're doing.
## Add -- --live (with a live backend) to watch the real models instead of the stub.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("VILLAGE SMOKE FAILED: " + reason)
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
	var live := "--live" in OS.get_cmdline_user_args() # With the real models: the decider plans, the voice speaks the chat.
	if not check(health.ok and (live or str(health.data.ai.mode) == "stub"), "Start the backend with AI_MODE=stub for this test"):
		return
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene._enter_run(created.data, false)
	await process_frame
	# Walk west along the road and up to within sight of the smithy, where Mara and Jory fall into talk. (The gate
	# guards' patrols only line up by chance, and a pair doesn't small-talk again for ten minutes, D-48.)
	var cells := []
	for x in range(47, 18, -1):
		cells.append([x, 67])
	for y in range(66, 33, -1):
		cells.append([19, y])
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
		if not check(reply.ok, "Could not walk up the road"):
			return
		scene._accept_state(reply.data.state)
	scene.predicted_cell = Vector2i(19, 34)
	scene.player.position = scene._cell_center(19, 34)
	scene.camera.reset_smoothing()
	var planned := false
	var chat := ""
	for i in 480:
		var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/explore" % scene.run_state.run_id,
			{"elapsed_ms": 1000, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("explore")})
		if reply.ok:
			scene._accept_state(reply.data.state)
		while scene.thinking_active:
			await process_frame
		for npc in scene.run_state.npcs:
			var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
			planned = planned or their_mind.has("next_agenda_at")
			var said = their_mind.get("said")
			if typeof(said) == TYPE_DICTIONARY and ":chat:" in str(said.get("key", "")):
				chat = str(npc.id)
		if not chat.is_empty():
			break
	if not check(planned, "Nobody planned their day"):
		return
	if not check(not chat.is_empty(), "Nobody fell into talk within eight minutes"):
		return
	await create_timer(2.6).timeout # The second speaker answers a beat later.
	var bubble := scene.get_node_or_null("NPCs/%s/Speech/Words" % chat) as Label
	if not check(bubble != null and not bubble.text.is_empty(), "No speech bubble for the chat"):
		return
	if not check(scene.run_state.learned.any(func(c: Dictionary) -> bool: return c.has("overheard")) or
			scene.player.position.distance_to(scene.get_node("NPCs/" + chat).position) > 5 * 32,
			"Close enough to overhear, but nothing went into the journal"):
		return
	await screenshot("village-chat")
	scene.ui.card.show_for(chat)
	await process_frame
	var words := PackedStringArray()
	for label in scene.ui.card.body.get_children():
		if label is Label:
			words.append(label.text)
	if not check("Seems " in "\n".join(words), "The inspect card doesn't say how they seem: " + "\n".join(words)):
		return
	await screenshot("village-inspect")
	print("VILLAGE SMOKE PASSED: ", chat, " talked; card: ", words[2] if words.size() > 2 else "")
	quit(0)
