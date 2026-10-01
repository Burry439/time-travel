extends SceneTree
## The tutorial, "The first morning" (GDD D-50, D-52). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --headless --path . --script res://tools/smoke_tutorial.gd  [-- --capture]
## The title's Training screen starts one (Basics, Play). The first card is up, big and centred, and the world waits (no clock).
## Next through the cards; the banner and the marker show the task; walking into the ring, a closer look, picking
## things up and opening the pack each move the story on, one step at a time. Then, in a developer tutorial
## journey: "Type it for me" fills the dialogue bar for Jory; the steps the stub judge can't do are skipped; Kade
## lends his staff, Pack & gear puts it in hand, the bout is fought (and a help card stops even the bout's clock);
## the last cards lead to the level complete screen. Finally the wainwright's notebook opens, and its Type it for me works.
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
	await create_timer(0.5).timeout
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


## The button on the Pack & gear row for this thing (its label names it).
func row_button(root_node: Node, item: String, text: String) -> Button:
	for row in root_node.find_children("*", "HBoxContainer", true, false):
		var named := false
		for child in row.get_children():
			named = named or (child is Label and item in (child as Label).text.to_lower())
		if named:
			for child in row.get_children():
				if child is Button and (child as Button).text == text:
					return child
	return null


## The Play button on a level's card on the Training screen.
func level_button(title: String) -> Button:
	for card in scene.ui.modal.find_children("*", "PanelContainer", true, false):
		var named := false
		for label in card.find_children("*", "Label", true, false):
			named = named or title in (label as Label).text
		var buttons: Array[Node] = card.find_children("*", "Button", true, false)
		if named and buttons.size() == 1 and (buttons[0] as Button).text.begins_with("Play"): # The card itself.
			return buttons[0]
	return null


func step_id() -> String:
	var tutorial = scene.run_state.get("tutorial")
	if typeof(tutorial) != TYPE_DICTIONARY or tutorial.get("done", false):
		return "done"
	return str(scene.ui.guide.steps[int(tutorial.step)].id)


func wait_for_step(wanted: String, seconds := 20.0) -> bool:
	var waited := 0.0
	while step_id() != wanted and waited < seconds:
		await create_timer(0.25).timeout
		waited += 0.25
	return step_id() == wanted


## Press Next through whatever cards are up (praise, then the step's own), and wait for the story to hear it.
func read_cards() -> void:
	for _i in 30:
		await create_timer(0.15).timeout
		if scene.ui.guide.is_open():
			scene.ui.guide._next()
		elif not scene.ui.guide.sending:
			await create_timer(0.3).timeout
			if not scene.ui.guide.is_open():
				return


func walk(cells: Array) -> bool:
	for i in range(0, cells.size(), 20):
		var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
			{"cells": cells.slice(i, i + 20), "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("move")})
		if not reply.ok:
			return false
		scene.accept_state(reply.data.state)
	var last: Array = cells[-1]
	scene.predicted_cell = Vector2i(last[0], last[1])
	scene.player.position = scene.cell_center(last[0], last[1])
	return true


func take(object_id: String) -> bool:
	var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/quick" % scene.run_state.run_id,
		{"verb": "take", "object_id": object_id, "expected_version": scene.run_state.event_seq, "request_id": scene.request_id("take")})
	if reply.ok:
		scene.accept_state(reply.data.state)
	return reply.ok


func skip() -> void:
	var reply: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs/%s/tutorial/skip" % scene.run_state.run_id, {})
	if reply.ok:
		scene.accept_state(reply.data.state)
	await read_cards() # The next step counts only once its cards are read.


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene.net.api(HTTPClient.METHOD_GET, "/health")
	if not check(health.ok and str(health.data.ai.mode) == "stub", "Start the backend with AI_MODE=stub for this test"):
		return
	var training := find_button(scene.menu, "Training")
	if not check(training != null, "No Training button on the title"):
		return
	training.pressed.emit() # The Training screen (D-59): the first morning is in Basics, for now.
	var start: Button = null
	for _i in 40:
		await create_timer(0.1).timeout
		start = level_button("The first morning") if scene.ui.modal_kind == "training" else null
		if start:
			break
	if not check(start != null, "No first morning to play on the Training screen"):
		return
	start.pressed.emit()
	for _i in 40:
		await create_timer(0.1).timeout
		if not scene.run_state.is_empty():
			break
	if not check(scene.run_state.get("scenario") == "tutorial" and step_id() == "welcome", "The tutorial didn't start"):
		return
	# The first card: big, centred, and the world waits.
	await create_timer(0.3).timeout
	var guide: Control = scene.ui.guide
	if not check(guide.is_open() and "device" in str(guide.words.text), "No first card"):
		return
	var centre: Vector2 = guide.panel.get_global_rect().get_center()
	var view: Vector2 = scene.ui.root.size
	if not check(absf(centre.x - view.x * 0.5) < view.x * 0.1 and guide.panel.size.x >= 700, "The card isn't big and centred"):
		return
	var clock := int(scene.run_state.sim_time_ms)
	await create_timer(2.0).timeout
	if not check(int(scene.run_state.sim_time_ms) == clock and scene.ui.blocks_movement(), "The world didn't wait while the card was up"):
		return
	await screenshot("tutorial_card")
	await read_cards()
	if not check(await wait_for_step("walk"), "Reading the welcome didn't move on: " + step_id()):
		return
	await read_cards()
	if not check(guide.banner.visible and "ring" in guide.banner_text.text and guide.focus.visible, "No banner or marker for walking"):
		return
	await screenshot("tutorial_banner")
	if not check(await walk([[48, 67], [48, 66], [48, 65], [48, 64], [48, 63], [48, 62]]), "Could not walk up the road"):
		return
	if not check(await wait_for_step("look"), "Reaching the ring didn't move the story on: " + step_id()):
		return
	await read_cards()
	scene.ui.card.show_for("plantain_a") # Right-click: a closer look.
	if not check(await wait_for_step("take"), "A closer look didn't count: " + step_id()):
		return
	scene.ui.card.hide()
	await read_cards()
	if not check(await take("plantain_a"), "Could not pick up the plantain"):
		return
	if not check(await wait_for_step("gather"), "Picking up the plantain didn't count: " + step_id()):
		return
	await read_cards()
	if not check(await take("flint_a") and await take("grass_a"), "Could not pick up the flint and grass"):
		return
	if not check(await wait_for_step("pack"), "Picking up two more didn't count: " + step_id()):
		return
	await read_cards()
	scene.ui.pack.open()
	if not check(await wait_for_step("smithy"), "Opening the pack didn't count: " + step_id()):
		return
	await read_cards()
	scene.ui.close_modal_now()
	# H: the step's help, as cards.
	guide.open_help()
	if not check(guide.is_open() and "arrow" in str(guide.words.text), "H didn't show the step's help"):
		return
	guide._next()
	await screenshot("tutorial_keys") # "Hold {Shift}...": a key cap.
	await read_cards()
	# A developer tutorial journey for the rest.
	var created: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer", "scenario": "tutorial"})
	scene.enter_run(created.data, false)
	await process_frame
	for _i in 8: # welcome, walk, look, take, gather, pack, smithy
		if step_id() == "talk":
			break
		await skip()
	if not check(step_id() == "talk", "Skipping didn't reach 'Talking': " + step_id()):
		return
	# The talk step's cards end with the words and Type it for me.
	guide.pages.clear()
	for text in guide.steps[guide.current_step()].cards:
		guide.pages.append({"text": text, "kind": "card", "step": guide.current_step()})
	guide.page = guide.pages.size() - 1
	guide._show_page()
	if not check(guide.suggest_box.visible and guide.type_button.visible, "No Type it for me on the talk card"):
		return
	await guide._type_it()
	if not check(scene.ui.bar.visible and scene.ui.bar.target == "npc_jory_venn" and
			scene.ui.bar.line.text == "Let me see your arm.", "Type it for me didn't fill the bar for Jory"):
		return
	scene.ui.bar.close()
	for _i in 4: # talk, remedy, treat (the stub judge can't make a poultice)
		if step_id() == "kade":
			break
		await skip()
	if not check(step_id() == "kade", "Skipping didn't reach Kade: " + step_id()):
		return
	await read_cards()
	var lent := false
	for _i in 160:
		await create_timer(0.25).timeout
		if str(scene.run_state.objects.get("practice_sword", {}).get("holder_id", "")) == "player":
			lent = true
			break
	if not check(lent, "Kade never lent the practice sword"):
		return
	if not check(await wait_for_step("arm"), "Being lent the sword didn't move on: " + step_id()):
		return
	await read_cards()
	scene.ui.pack.open()
	await process_frame
	var right := row_button(scene.ui.modal, "practice sword", "Right hand")
	if not check(right != null, "No 'Right hand' button for the sword in Pack & gear"):
		return
	right.pressed.emit()
	for _i in 40: # The sword in hand, and Pack & gear drawn again, before the shield.
		await create_timer(0.1).timeout
		if scene.run_state.player.get("equipped", {}).get("right") == "practice_sword" and not scene.request_busy:
			break
	await create_timer(0.3).timeout
	var left := row_button(scene.ui.modal, "wicker shield", "Left hand")
	if not check(left != null, "No 'Left hand' button for the shield in Pack & gear"):
		return
	left.pressed.emit()
	if not check(await wait_for_step("bout"), "Sword and shield in hand didn't move the story on: " + step_id()):
		return
	var kit: Dictionary = scene.run_state.player.get("equipped", {})
	if not check(kit.get("right") == "practice_sword" and kit.get("left") == "wicker_shield",
			"Both hands aren't full (D-57): " + str(kit)):
		return
	scene.ui.close_modal_now()
	await read_cards()
	var fought := false
	var paused_checked := false
	for _i in 160:
		await create_timer(0.25).timeout
		if scene.in_fight():
			fought = true
			if not paused_checked: # A help card stops even the bout's clock.
				paused_checked = true
				guide.open_help()
				await create_timer(0.6).timeout
				var during := int(scene.run_state.sim_time_ms)
				await create_timer(1.5).timeout
				if not check(int(scene.run_state.sim_time_ms) == during, "The bout's clock ran while a card was up"):
					return
				await read_cards()
			var kade: Dictionary = scene.ui.npc_record("npc_kade_east")
			var toward := Vector2(float(kade.x), float(kade.y)) - Vector2(scene.run_state.player.x, scene.run_state.player.y)
			if toward.length() > 0.5:
				scene.facing_row = scene.facing_for(toward.normalized())
			await scene.fight.strike("right")
		elif fought or step_id() != "bout":
			break
	if not check(fought, "The bout never started"):
		return
	if not check(await wait_for_step("why"), "The bout's end didn't move the story on: " + step_id()):
		return
	await skip() # why (Kade asks what brings you here)
	await skip() # steel
	if not check(await wait_for_step("fire"), "Not at the fire: " + step_id()):
		return
	await skip() # fire (the stub judge can't make a real one)
	await skip() # captain (Kade's word; the stub voice can't let you in); then the last step's cards are read.
	for _i in 20:
		await create_timer(0.2).timeout
		if scene.ui.modal_kind == "level_complete":
			break
	if not check(step_id() == "done" and scene.ui.modal_kind == "level_complete", "No level complete screen: " + step_id()):
		return
	await screenshot("tutorial_complete")
	# The wainwright's notebook (D-52).
	scene.ui.close_modal_now()
	var village: Dictionary = await scene.net.api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	scene.enter_run(village.data, false)
	await process_frame
	var notebook: Dictionary = scene.run_state.objects.get("yard_recipe_book", {})
	if not check(str(notebook.get("readable", "")) == "recipe_book", "No wainwright's notebook in a new journey"):
		return
	scene.ui.open_book(notebook)
	await process_frame
	var spear := find_button(scene.ui.modal, "Spear")
	if not check(scene.ui.modal_kind == "book" and spear != null, "The notebook didn't open with its recipes"):
		return
	spear.pressed.emit()
	await process_frame
	await screenshot("recipe_book")
	var type_it := find_button(scene.ui.modal, "Type it for me")
	if not check(type_it != null, "No Type it for me on a recipe"):
		return
	type_it.pressed.emit()
	await process_frame
	if not check(scene.ui.bar.visible and "spearhead" in scene.ui.bar.line.text, "The recipe's words didn't reach the bar"):
		return
	print("TUTORIAL SMOKE PASSED: %d steps, bout: %s" % [guide.steps.size(),
		str(scene.run_state.journal.filter(func(e) -> bool: return str(e.get("category", "")).begins_with("spar_")).map(
			func(e) -> String: return str(e.category)))])
	quit(0)
