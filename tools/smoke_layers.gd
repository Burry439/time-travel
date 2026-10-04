extends SceneTree
## The game layers and the journal (GDD D-55). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --path . --script res://tools/smoke_layers.gd  [-- --capture]
## In the main game: the goal tracker shows the long goal, then the newest lead, then a pinned one with a ring on
## the person it's about; a change in someone's standing brings a toast; something you made brings the reveal card;
## the journal opens on Goals, and every page (People with the conversation, Deeds, the log) builds.
## The state changes here are the client's own copy: this checks what the UI shows, not what the world decides.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("LAYERS SMOKE FAILED: " + reason)
		quit(1)
	return condition


func shot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/%s.png" % name)


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not check(created.ok, "Start the backend with AI_MODE=stub first"):
		return
	scene.enter_run(created.data, false)
	await create_timer(0.8).timeout
	scene.gameplay_active = false # Hold the world still: no clock syncs replacing this copy of the state.
	for _i in 100: # Nor a thought already on its way back, which would replace it too.
		if not scene.thinking_active:
			break
		await create_timer(0.1).timeout
	var ui: Control = scene.ui
	if not check(ui.hud.goal.text == "Find a way into the city", "The tracker doesn't start on the long goal: " + ui.hud.goal.text):
		return
	# Two leads, as if two people had told you things; the newest shows first.
	var npcs: Array = scene.run_state.npcs
	var far: Dictionary = npcs[0]
	for npc in npcs: # The farthest person from you, so the marker's ring shows.
		if Vector2(npc.x, npc.y).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y)) \
				> Vector2(far.x, far.y).distance_to(Vector2(scene.run_state.player.x, scene.run_state.player.y)):
			far = npc
	var near: Dictionary = npcs[1] if npcs[0] == far else npcs[0]
	scene.run_state.learned = [
		{"npc_id": far.id, "name": far.name, "said": "They know the gate.", "lead": "Ask %s about the gate" % far.name},
		{"npc_id": near.id, "name": near.name, "said": "Water's short.", "lead": "Bring %s water" % near.name}]
	scene.run_state.journal.append({"kind": "talk", "npc_id": near.id, "text": "Is there water anywhere near?",
		"reply": "The well's gone dry. Bring me water and I won't forget it.", "reason": ""})
	ui.hud.refresh()
	if not check(ui.hud.goal.text == "Bring %s water" % near.name, "The tracker doesn't show the newest lead: " + ui.hud.goal.text):
		return
	ui.layers.pin("Ask %s about the gate" % far.name)
	await process_frame
	await process_frame # The marker moves in the layers' own _process, after this signal.
	if not check(ui.hud.goal.text.begins_with("◆") and far.name in ui.hud.status.text,
			"Pinned, the tracker doesn't follow it: " + ui.hud.goal.text):
		return
	if not check(ui.layers.ring.visible, "The pinned lead's person isn't marked"):
		return
	# Someone's view of you changes: a toast. Something you made: the reveal card.
	var mind: Dictionary = near.get("mind", {}) if typeof(near.get("mind")) == TYPE_DICTIONARY else {}
	mind["standing"] = "friendly"
	near["mind"] = mind
	var made: Dictionary = scene.run_state.objects.values()[0].duplicate(true)
	made.id = "smoke_made"
	made.name = "reed whistle"
	made.created_by = "player"
	made.holder_id = "player"
	scene.run_state.objects["smoke_made"] = made
	ui.layers.refresh()
	await process_frame
	if not check(ui.layers.toasts.get_child_count() >= 1, "No toast for a change in standing or a new deed"):
		return
	if not check(ui.layers.reveal.visible and ui.layers.reveal_title.text == "Reed Whistle", "No reveal card for something made"):
		return
	await shot("layers_toasts")
	# A successful change to an authored object keeps its identity and is visible without making another item.
	var count_before: int = scene.run_state.objects.size()
	var changed: Dictionary = scene.run_state.objects.branch_a
	changed.holder_id = "player"
	changed.revision = int(changed.get("revision", 0)) + 1
	changed.picture_event_id = 100
	changed.attributes = [{"name": "shaved_grip", "value": "A carved grip wrapped with leather.", "status": "observed"}]
	# Its binding changes too; the reveal should show the worked object, not an empty card for the cord.
	var binding: Dictionary = scene.run_state.objects.cord_a
	binding.revision = int(binding.get("revision", 0)) + 1
	binding.picture_event_id = 100
	binding.x = scene.run_state.player.x
	binding.y = scene.run_state.player.y
	ui.layers.refresh()
	if not check(ui.layers.reveal.visible and ui.layers.reveal_title.text.begins_with("Changed: ")
			and "carved grip" in ui.layers.reveal_text.text and scene.run_state.objects.size() == count_before,
			"An existing object's changed grip has no clear reveal"):
		return
	ui.card.show_for("branch_a")
	var inspected := false
	for label in ui.card.find_children("*", "Label", true, false):
		inspected = inspected or "carved grip" in label.text
	if not check(inspected, "Inspect hides the object's new physical attributes"):
		return
	ui.card.hide()
	ui.layers.reveal.hide()
	ui.layers.refresh()
	if not check(not ui.layers.reveal.visible, "Refreshing unchanged state repeats the changed-object reveal"):
		return
	# The journal: Goals first, then every page.
	ui.open_journal()
	await process_frame
	if not check(ui.modal_kind == "journal", "The journal didn't open"):
		return
	var book: Node = null
	for node in ui.find_children("*", "VBoxContainer", true, false):
		if node.get_script() == preload("res://scripts/ui/journal_book.gd"):
			book = node
	if not check(book != null and book.tab == "goals", "The journal doesn't open on Goals"):
		return
	await shot("journal_goals")
	for tab in ["people", "deeds", "made", "device", "log", "map"]:
		book.show_tab(tab)
		await process_frame
		if not check(book.tab == tab and is_instance_valid(book.page), "The %s page didn't build" % tab):
			return
	book.open_person = str(near.id)
	book.show_tab("people")
	await process_frame
	var listed := false
	for node in book.page.find_children("*", "Label", true, false):
		listed = listed or str(near.name) in node.text
	if not check(listed, "The People page doesn't list someone who's friendly"):
		return
	await shot("journal_people")
	book.show_tab("deeds")
	await shot("journal_deeds")
	ui.close_modal_now()
	ui.layers.pin("Ask %s about the gate" % far.name) # Unpin, so this journey leaves nothing behind.
	if not check(ui.layers.pinned.is_empty(), "Couldn't unpin"):
		return
	print("LAYERS SMOKE PASSED")
	quit(0)
