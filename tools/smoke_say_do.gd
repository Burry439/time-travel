extends SceneTree
## Say or Do (GDD D-55). Needs the backend with AI_MODE=stub:
##   $env:AI_MODE='stub'; ./tools/run_m0.ps1
##   Godot --path . --script res://tools/smoke_say_do.gd  [-- --capture]
## The "[E] Pick up…" prompt shows over the nearest thing. The bar opens on Do when you face nobody, on Say when you
## face someone; Tab flips it; the preview says how the line will be taken; a Do line reaches the backend as a deed
## chosen by the player (no guessing). A book held in hand opens with Space.
var scene: Node2D
var capture := false


func _initialize() -> void:
	capture = "--capture" in OS.get_cmdline_user_args()
	call_deferred("_run")


func check(condition: bool, reason: String) -> bool:
	if not condition:
		push_error("SAY/DO SMOKE FAILED: " + reason)
		quit(1)
	return condition


func screenshot(name: String) -> void:
	if not capture:
		return
	await create_timer(0.4).timeout
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png("res://docs/screenshots/" + name + ".png")


func tab() -> void:
	var key := InputEventKey.new()
	key.keycode = KEY_TAB
	key.pressed = true
	scene.ui.bar._on_line_key(key)


func _run() -> void:
	scene = load("res://scenes/main.tscn").instantiate()
	root.add_child(scene)
	await process_frame
	var created: Dictionary = await scene._api(HTTPClient.METHOD_POST, "/runs", {"mode": "developer"})
	if not check(created.ok, "Start the backend with AI_MODE=stub first"):
		return
	scene._enter_run(created.data, false)
	await create_timer(1.0).timeout
	# The E prompt over the nearest thing (the start of the south road is strewn with things).
	if not check(scene.ui.hud.prompt.visible and "[ E ]" in scene.ui.hud.prompt_text.text, "No [E] prompt near the road's things"):
		return
	await screenshot("prompt_e")
	# Alone: the bar opens on Do.
	var bar = scene.ui.bar
	bar.open()
	await process_frame
	if not check(bar.mode == "do" and "Do something" in bar.line.placeholder_text, "Alone, the bar didn't open on Do"):
		return
	tab()
	if not check(bar.mode == "say" and "Say something" in bar.line.placeholder_text, "Tab didn't switch to Say"):
		return
	bar.line.text = "Good day"
	bar._show_preview()
	if not check(bar.hint.text.begins_with("You'll say"), "No speech preview: " + bar.hint.text):
		return
	await screenshot("bar_say")
	# One line, both (D-57): Tab halfway through quotes the words said so far; the deed goes on in red.
	bar.line.put("", "say")
	bar.line.insert_text_at_caret("Look at this")
	tab()
	bar.line.insert_text_at_caret("hold up the flint shard")
	if not check(bar.line.text == "“Look at this” hold up the flint shard" and bar.mode == "do",
			"Tab mid-line didn't quote the words and switch to Do: " + bar.line.text):
		return
	tab()
	bar.line.insert_text_at_caret("Ever seen one this sharp?")
	var sent: Dictionary = bar.line.payload()
	if not check(bar.mode == "say" and sent.mode == "do"
			and sent.text == "“Look at this” hold up the flint shard “Ever seen one this sharp?”",
			"A mixed line didn't go out as a deed with words: " + str(sent)):
		return
	var colours: Dictionary = bar.line.colours_for(bar.line.text)
	if not check(colours[0].color == bar.SAY_COLOUR and colours[14].color == bar.DO_COLOUR, "The line isn't blue and red: " + str(colours)):
		return
	bar._show_preview()
	if not check("blue" in bar.hint.text, "No preview for a line that's both: " + bar.hint.text):
		return
	await screenshot("bar_both")
	tab() # Out of the empty-quoted words at the end...
	bar.line.put("", "do")
	bar.line.insert_text_at_caret("wave")
	tab()
	tab() # ...and an empty pair of quotes, switched straight back, is taken away again.
	if not check(bar.line.text == "wave", "Empty quotes weren't taken away: " + bar.line.text):
		return
	bar.line.put("", "say")
	tab()
	bar.line.text = "pick up the fallen branch"
	bar._show_preview()
	if not check(bar.hint.text.begins_with("You'll do"), "No deed preview: " + bar.hint.text):
		return
	await screenshot("bar_do")
	bar.submit()
	for _i in 60:
		await create_timer(0.1).timeout
		if not scene.request_busy and not bar.waiting:
			break
	if not check(str(bar.last_intent.get("how", "")) == "player" and str(bar.last_intent.get("kind", "")) == "do",
			"The backend didn't take the Do as given: " + str(bar.last_intent)):
		return
	bar.close()
	# Facing someone: the bar opens on Say.
	bar.open("npc_hessa_marr")
	await process_frame
	if not check(bar.mode == "say" and "Hessa" in bar.line.placeholder_text, "Facing Hessa, the bar didn't open on Say"):
		return
	bar.close()
	# A book in hand: Space reads it (the client's view of the state is enough for this check).
	var book: Dictionary = scene.run_state.objects.get("yard_recipe_book", {})
	if not check(not book.is_empty(), "No notebook in a new journey"):
		return
	book["holder_id"] = "player"
	scene.run_state.player["equipped"]["right"] = "yard_recipe_book"
	scene.fight.strike("right")
	await process_frame
	if not check(scene.ui.modal_kind == "book", "Space with the notebook in hand didn't open it"):
		return
	print("SAY/DO SMOKE PASSED")
	quit(0)
