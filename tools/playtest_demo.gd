extends SceneTree
## A scripted playthrough of the main game with the live models (GDD D-55, Milestone D): the bug bash's first pass.
## Needs the backend running live (no AI_MODE=stub):
##   ./tools/run_m0.ps1
##   Godot --path . --script res://tools/playtest_demo.gd  [-- --capture]
## It plays what a new player would do, through the same UI calls a click or a key makes:
##   talk to Hessa (Say), ask the device what to do, gather in the wainwright's yard, make something (Do),
##   read the notebook, go up to the gate and talk to the guard who stops you, then open every journal page.
## Nothing here asserts what a person says. It reports every step (time, outcome, the words) and ends with a list
## of BLOCKERS (no reply, a stuck bar, a request that failed, a script error) and NOTES (slow or odd).
var scene: Node2D
var capture := false
var blockers: PackedStringArray = []
var notes: PackedStringArray = []
var steps: Array = []


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func blocker(text: String) -> void:
	blockers.append(text)
	print("  !! BLOCKER: ", text)


func note(text: String) -> void:
	notes.append(text)
	print("  .. note: ", text)


func shot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.5).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/playtest_%s.png" % name)


## Wait for what's in flight (a round, an attempt, a walk) to finish; false if it never did.
func settle(limit_s := 120.0) -> bool:
	await process_frame
	var waited := 0.0
	while waited < limit_s:
		if not scene.request_busy and not scene.ui.bar.round_playing and not scene.ui.bar.waiting:
			return true
		await create_timer(0.1).timeout
		waited += 0.1
	return false


## Someone stopped the stranger (a halt, a confrontation): note who and why, and walk away as a player would.
func clear_encounter(why: String) -> void:
	if not scene.in_encounter():
		return
	var encounter: Dictionary = scene.run_state.get("encounter", {})
	note("%s: stopped by %s (%s): %s" % [why, encounter.get("participants", []), encounter.get("reason", ""),
		words_of(encounter.get("log", [])).left(200)])
	for attempt in 3:
		if not scene.in_encounter():
			break
		scene.ui.bar.open()
		await process_frame
		scene.ui.bar.escape()
		await settle()
	if scene.in_encounter():
		blocker("couldn't walk away from an encounter (%s)" % why)
	scene.ui.bar.close()


## Wait until the client would take a click or a line: nothing in flight, no walk syncing. The playtest moves
## through the API directly, so it waits for the client's own clock sync to settle, as a player's hand would.
func idle() -> void:
	for i in 100:
		if not scene.request_busy and not scene.movement_sync_active and not scene.sync_error and scene.gameplay_active:
			return
		await create_timer(0.1).timeout
	note("the client stayed busy for 10 s (busy %s, syncing %s, sync error %s)" % [scene.request_busy,
		scene.movement_sync_active, scene.sync_error])


## Walk along waypoints, one straight line at a time (the server checks every step).
func walk(points: Array) -> bool:
	for point in points:
		for attempt in 12:
			var here := Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
			if here == point:
				break
			var cells := []
			while here != point and cells.size() < 20:
				here += Vector2i(signi(point.x - here.x), signi(point.y - here.y))
				cells.append([here.x, here.y])
			var reply: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs/%s/move" % scene.run_state.run_id,
				{"cells": cells, "expected_version": scene.run_state.event_seq, "request_id": scene._request_id("move")})
			if typeof(reply.data) == TYPE_DICTIONARY and reply.data.has("state"):
				scene._accept_state(reply.data.state)
			if not reply.ok:
				var why := str(reply.data.get("detail", {}).get("reason", "")) if typeof(reply.data) == TYPE_DICTIONARY \
					and typeof(reply.data.get("detail")) == TYPE_DICTIONARY else ""
				if why == "encounter_active":
					await clear_encounter("walking to %s" % point)
					continue
				note("walk to %s refused at %s: %s" % [point, here, JSON.stringify(reply.data).left(160)])
				break
		scene.predicted_cell = Vector2i(int(scene.run_state.player.x), int(scene.run_state.player.y))
		scene.player.position = scene._cell_center(scene.predicted_cell.x, scene.predicted_cell.y)
	await create_timer(0.6).timeout
	await idle()
	return true


func step(name: String) -> Dictionary:
	print("\n== ", name)
	var record := {"name": name, "started": Time.get_ticks_msec()}
	steps.append(record)
	return record


func done(record: Dictionary, summary: String) -> void:
	record["ms"] = Time.get_ticks_msec() - int(record.started)
	record["summary"] = summary
	print("  -> (%.1f s) %s" % [record.ms / 1000.0, summary])
	if record.ms > 25000:
		note("%s took %.1f s" % [record.name, record.ms / 1000.0])


## Say or do something in the bar, to someone (or no one), and wait for the world's answer.
func bar_line(text: String, mode: String, to := "") -> Dictionary:
	await idle()
	if not scene.ui.bar.visible:
		scene.ui.bar.open(to)
	elif not to.is_empty() and scene.ui.bar.target != to:
		scene.ui.bar.open(to)
	await process_frame
	scene.ui.bar.set_mode(mode, true)
	scene.ui.bar.line.text = text
	var before_journal: int = scene.run_state.get("journal", []).size()
	scene.ui.bar.submit()
	var finished := await settle()
	if not finished:
		blocker("'%s' never finished (the bar stayed busy)" % text)
	var added: Array = scene.run_state.get("journal", []).slice(before_journal)
	if added.is_empty():
		var shown: Array = scene.ui.bar.own_log.filter(func(e) -> bool: return e.get("tone") == "bad")
		note("nothing happened for '%s' (target %s, encounter %s): %s" % [text.left(40), scene.ui.bar.target,
			scene.in_encounter(), shown[-1].text if not shown.is_empty() else "no message shown"])
	return {"finished": finished, "added": added}


func words_of(entries: Array) -> String:
	var lines := PackedStringArray()
	for entry in entries:
		match str(entry.get("kind", "")):
			"talk":
				lines.append("%s → “%s”" % [entry.get("npc_id", "?"), str(entry.get("reply", ""))])
			"npc":
				lines.append("%s: %s" % [entry.get("npc_id", "?"), str(entry.get("reason", ""))])
			_:
				lines.append("[%s/%s] %s" % [entry.get("kind", ""), entry.get("category", ""), str(entry.get("reason", ""))])
	return "\n     ".join(lines)


func take(object_id: String) -> String:
	var obj: Dictionary = scene.run_state.objects.get(object_id, {})
	if obj.is_empty():
		note("no object %s" % object_id)
		return ""
	await idle()
	scene._left_click(scene.ui.cursor.describe(object_id))
	await settle()
	var now: Dictionary = scene.run_state.objects.get(object_id, {})
	return "held" if now.get("holder_id") == "player" else "not held (%s)" % str(scene.run_state.get("last_action", {}).get("reason", ""))


func ask_device(question: String) -> String:
	var before: int = scene.run_state.get("device_log", []).size()
	scene.ui.device.open_ask()
	await scene.ui.device._ask(question)
	var log: Array = scene.run_state.get("device_log", [])
	scene.ui.close_modal_now()
	if log.size() <= before:
		blocker("the device didn't answer '%s'" % question)
		return ""
	return str(log[-1].get("text", ""))


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var health: Dictionary = await scene._api(HTTPClient.METHOD_GET, "/health")
	if not health.ok or str(health.data.get("ai", {}).get("mode", "")) == "stub":
		push_error("PLAYTEST: start the backend live (not stub): ./tools/run_m0.ps1")
		quit(1)
		return
	scene.ai_status = health.data.ai
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "normal"})
	scene._enter_run(created.data, false)
	await create_timer(1.0).timeout
	scene.ui.close_modal_now()
	scene.ui.hud.refresh()
	print("PLAYTEST run ", scene.run_state.run_id, "  tracker: ", scene.ui.hud.goal.text)

	# 1. Talk to Hessa at the inn: Say.
	var record := step("Talk to Hessa (Say)")
	await walk([Vector2i(44, 60), Vector2i(37, 54)])
	scene._left_click(scene.ui.cursor.describe("npc_hessa_marr"))
	await process_frame
	if not scene.ui.bar.visible:
		blocker("clicking Hessa didn't open the dialogue bar")
	if scene.ui.bar.mode != "say":
		note("the bar opened on %s for a person (expected Say)" % scene.ui.bar.mode)
	var said := await bar_line("Good day. I've come a long way and I'm trying to get into the city. Is there anything you need?", "say", "npc_hessa_marr")
	done(record, words_of(said.added))
	record = step("Hessa, second line (Say)")
	said = await bar_line("What would it take for the guards to let a stranger through?", "say", "npc_hessa_marr")
	done(record, words_of(said.added))
	await shot("hessa")
	scene.ui.bar.escape()
	await settle()
	scene.ui.bar.escape()
	await settle()
	if scene.ui.bar.visible or scene.in_encounter():
		blocker("couldn't walk away from Hessa (the bar or the encounter stayed)")
		scene.ui.bar.close()
	print("  leads: ", scene.ui.open_leads(), "   tracker: ", scene.ui.hud.goal.text, " / ", scene.ui.hud.status.text)

	await clear_encounter("after Hessa")
	# 2. The device as a coach.
	record = step("Ask the device what to do")
	done(record, await ask_device("What should I do next?"))

	# 2b. The demo's own path: do what Hessa asked, and she speaks for you to the captain.
	record = step("Accept Hessa's request (Say)")
	var deal_id := ""
	for claim in scene.run_state.get("learned", []):
		if claim.has("offer") and str(claim.get("npc_id", "")) == "npc_hessa_marr":
			deal_id = str(claim.offer)
	if deal_id.is_empty():
		note("Hessa made no request in two lines; asking directly")
		said = await bar_line("Is there some way I could help you, in return for a good word with the captain?", "say", "npc_hessa_marr")
		for claim in scene.run_state.get("learned", []):
			if claim.has("offer") and str(claim.get("npc_id", "")) == "npc_hessa_marr":
				deal_id = str(claim.offer)
	said = await bar_line("Yes, I'll gladly bring you the water.", "say", "npc_hessa_marr")
	var deal: Dictionary = scene.run_state.get("agreements", {}).get(deal_id, {})
	done(record, "deal %s: %s  %s" % [deal_id, deal.get("status", "none"), words_of(said.added)])
	if deal_id.is_empty():
		blocker("Hessa never asked for anything (no deal to do)")
	scene.ui.bar.escape()
	await settle()
	scene.ui.bar.close()
	record = step("Fetch the water (Do)")
	var bucket := await take("bucket_hessa")
	said = await bar_line("fill the wooden bucket with water from the trough", "do")
	var water := float(scene.run_state.objects.get("bucket_hessa", {}).get("water_l", 0))
	done(record, "bucket: %s; water %.1f l  %s" % [bucket, water, words_of(said.added)])
	if water <= 0.0:
		blocker("couldn't fill the bucket at the trough")
	scene.ui.bar.close()
	record = step("Give Hessa the water (Do)")
	said = await bar_line("hand Hessa the bucket of water", "do", "npc_hessa_marr")
	deal = scene.run_state.get("agreements", {}).get(deal_id, {})
	var deeds_now: Array = preload("res://scripts/ui/deeds.gd").compute(scene.run_state).map(func(d) -> String: return str(d.title))
	done(record, "deal: %s; deeds %s  %s" % [deal.get("status", "none"), deeds_now, words_of(said.added)])
	if str(deal.get("status", "")) != "fulfilled" and not deal_id.is_empty():
		blocker("the water was handed over but Hessa's deal isn't fulfilled (%s)" % deal.get("status", "none"))
	await shot("deal_done")
	scene.ui.bar.escape()
	await settle()
	scene.ui.bar.close()
	record = step("Wait for Hessa to speak to the captain")
	var vouched := false
	var waited_vouch := 0.0
	while waited_vouch < 90.0 and not vouched:
		await create_timer(1.0).timeout
		waited_vouch += 1.0
		var roderic: Dictionary = scene.ui.npc_record("npc_roderic_vale")
		for memory in roderic.get("mind", {}).get("memories", []):
			vouched = vouched or (memory.get("kind") == "vouch" and str(memory.get("by", "")) == "npc_hessa_marr")
	var hessa_job = scene.ui.npc_record("npc_hessa_marr").get("mind", {}).get("job")
	done(record, "vouched: %s after %.0f s; Hessa's job now %s" % [vouched, waited_vouch, JSON.stringify(hessa_job).left(120)])
	if not vouched and str(deal.get("status", "")) == "fulfilled":
		blocker("Hessa's deal was done but she never spoke to Roderic in 90 s")

	await clear_encounter("after the water")
	# 3. The wainwright's yard: gather, then make something (Do).
	record = step("Walk to the wainwright's yard and gather")
	await walk([Vector2i(56, 62), Vector2i(70, 60), Vector2i(80, 59)])
	var got := PackedStringArray()
	for id in ["yard_spearhead", "yard_ash_stave", "yard_thongs"]:
		got.append("%s: %s" % [id, await take(id)])
	done(record, ", ".join(got))
	record = step("Make a spear (Do)")
	var made_before: int = scene.run_state.objects.values().filter(func(o) -> bool: return o.get("created_by") == "player").size()
	scene.ui.bar.close()
	said = await bar_line("lash the iron spearhead onto the end of the ash stave with the leather thongs, to make a spear", "do")
	var made: Array = scene.run_state.objects.values().filter(func(o) -> bool: return o.get("created_by") == "player")
	done(record, words_of(said.added) + ("   MADE: " + str(made[-1].name) if made.size() > made_before else "   (nothing made)"))
	if made.size() > made_before and not scene.ui.layers.reveal.visible:
		blocker("something was made but no reveal card showed")
	await shot("made")
	scene.ui.bar.close()

	# 4. The notebook.
	record = step("Read the wainwright's notebook")
	var book := await take("yard_recipe_book")
	var readable: Dictionary = scene.run_state.objects.get("yard_recipe_book", {})
	scene.ui.open_book(readable)
	await process_frame
	done(record, "%s; open: %s" % [book, scene.ui.modal_kind])
	if scene.ui.modal_kind != "book" and not readable.is_empty():
		note("the notebook didn't open as a book (modal: %s)" % scene.ui.modal_kind)
	scene.ui.close_modal_now()

	await clear_encounter("after the yard")
	# 5. The gate: a guard stops you.
	record = step("Go up to the gate")
	await walk([Vector2i(70, 50), Vector2i(56, 34), Vector2i(48, 22), Vector2i(48, 17)])
	var waited := 0.0
	while waited < 30.0 and not scene.ui.bar.showing_encounter():
		await create_timer(0.2).timeout
		waited += 0.2
	await settle()
	if not scene.ui.bar.showing_encounter():
		note("no guard stopped the stranger at the gate within 30 s")
		done(record, "no halt")
		record = step("Ask Roderic to let you in (Say, walking up)")
		scene._left_click(scene.ui.cursor.describe("npc_roderic_vale"))
		await process_frame
		said = await bar_line("Captain, Hessa the innkeeper has spoken for me: I brought her water when she needed it. Will you let me in?", "say", "npc_roderic_vale")
		done(record, "admitted: %s  %s" % [typeof(scene.run_state.get("admitted")) == TYPE_DICTIONARY, words_of(said.added)])
		await shot("gate")
		scene.ui.bar.escape()
		await settle()
		scene.ui.bar.escape()
	else:
		var guard := str(scene.ui.bar.target)
		done(record, "halted by %s: %s" % [guard, words_of(scene.run_state.encounter.get("log", []))])
		record = step("Talk to the guard (Say)")
		said = await bar_line("I mean no harm. I'm a traveller and I need shelter. What would let me in?", "say", guard)
		done(record, words_of(said.added))
		await shot("gate")
		record = step("Ask Roderic to let you in (Say)")
		said = await bar_line("Captain, Hessa the innkeeper has spoken for me: I brought her water when she needed it. Will you let me in?", "say", "npc_roderic_vale")
		var admitted = scene.run_state.get("admitted")
		done(record, "admitted: %s  %s" % [typeof(admitted) == TYPE_DICTIONARY, words_of(said.added)])
		if typeof(admitted) == TYPE_DICTIONARY:
			await create_timer(1.0).timeout
			await shot("admitted")
			print("  victory panel: ", scene.victory_panel.visible)
		scene.ui.bar.escape()
		await settle()
		scene.ui.bar.escape()

	# 6. The device again, now it knows more.
	record = step("Ask the device again")
	done(record, await ask_device("I've talked to Hessa and the guard. What's my best next step?"))

	# 7. The journal, with real data.
	record = step("Journal pages")
	scene.ui.open_journal()
	await process_frame
	var journal: Node = null
	for node in scene.ui.find_children("*", "VBoxContainer", true, false):
		if node.get_script() == preload("res://scripts/ui/journal_book.gd"):
			journal = node
	var built := PackedStringArray()
	if journal == null:
		blocker("the journal didn't open")
	else:
		await shot("journal_goals")
		for tab in ["people", "deeds", "made", "device", "log", "map"]:
			journal.show_tab(tab)
			await process_frame
			built.append("%s:%d" % [tab, journal.page.find_children("*", "Label", true, false).size()])
		journal.open_person = "npc_hessa_marr"
		journal.show_tab("people")
		await shot("journal_people")
	scene.ui.close_modal_now()
	var deeds: Array = preload("res://scripts/ui/deeds.gd").compute(scene.run_state).map(func(d) -> String: return str(d.title))
	done(record, "pages %s; deeds %s" % [", ".join(built), deeds])

	print("\n==== PLAYTEST REPORT ====")
	for item in steps:
		print("%-40s %6.1f s" % [item.name, float(item.get("ms", 0)) / 1000.0])
	print("device log: %d entries; leads: %d; standing: %s" % [scene.run_state.get("device_log", []).size(),
		scene.ui.open_leads().size(), scene.run_state.npcs.filter(func(n) -> bool: return typeof(n.get("mind")) == TYPE_DICTIONARY and n.mind.get("standing", "unknown") != "unknown").map(func(n) -> String: return "%s=%s" % [n.name, n.mind.standing])])
	print("BLOCKERS (%d):" % blockers.size())
	for item in blockers:
		print("  - ", item)
	print("NOTES (%d):" % notes.size())
	for item in notes:
		print("  - ", item)
	print("PLAYTEST DONE")
	quit(0 if blockers.is_empty() else 2)
