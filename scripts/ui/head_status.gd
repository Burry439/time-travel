extends Node2D
## Small signs over a person's head, from state the client already has (GDD D-35):
## "…" while they're thinking or replying, "!" when frightened, red crossed blades when they mean
## violence (attacking or seizing), a gold mark for a few seconds after they warm to you, and a thin
## health bar when hurt. Never numbers.

const UITheme := preload("res://scripts/ui/ui_theme.gd")

var game: Node2D
var npc_id := ""
var clock := 0.0
var signs: Array[String] = []
var health := 100.0


func _process(delta: float) -> void:
	clock += delta
	var npc: Dictionary = game.ui.npc_record(npc_id)
	var next: Array[String] = []
	health = 100.0
	if not npc.is_empty() and npc.get("alive", true):
		health = float(npc.get("health", 100))
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		var job = their_mind.get("job")
		var current = game.run_state.get("encounter")
		var intent := ""
		if typeof(current) == TYPE_DICTIONARY:
			intent = str((current.get("intents", {}).get(npc_id) if typeof(current.get("intents", {}).get(npc_id)) == TYPE_DICTIONARY else {}).get("action", ""))
		# "…" means reacting to the stranger (or face to face), not planning an ordinary day.
		var thinking: bool = game.run_state.get("pending_minds", []).any(func(p) -> bool:
			return typeof(p) == TYPE_DICTIONARY and str(p.get("npc_id", "")) == npc_id \
				and str(p.get("kind", "")) in ["decide", "round"])
		if game.ui.bar.waiting and typeof(current) == TYPE_DICTIONARY and npc_id in current.get("participants", []):
			thinking = true
		if thinking:
			next.append("thinking")
		if intent in ["attack", "seize"] or (typeof(job) == TYPE_DICTIONARY and str(job.get("kind", "")) == "attack"):
			next.append("hostile")
		elif float(their_mind.get("feelings", {}).get("fear", 0)) > 0.6 				or float(their_mind.get("feelings", {}).get("anger", 0)) >= 0.6:
			next.append("alarmed") # Frightened or angry: something just happened to them.
		if float(game.warm_until.get(npc_id, 0.0)) > Time.get_ticks_msec() / 1000.0:
			next.append("warm")
	if next != signs or not signs.is_empty() or health < 100.0:
		signs = next
		queue_redraw()


func _draw() -> void:
	if health < 100.0:
		draw_rect(Rect2(-20, 2, 40, 5), Color(0.1, 0.06, 0.03, 0.8))
		draw_rect(Rect2(-19, 3, 38 * clampf(health / 100.0, 0, 1), 3),
			Color(0.75, 0.2, 0.15).lerp(Color(0.45, 0.65, 0.25), health / 100.0))
	var x := -(signs.size() - 1) * 13.0
	for sign in signs:
		_sign(sign, Vector2(x, -10))
		x += 26.0


func _sign(kind: String, at: Vector2) -> void:
	var ink := Color(UITheme.INK, 0.9)
	match kind:
		"thinking":
			draw_rect(Rect2(at + Vector2(-14, -8), Vector2(28, 16)), UITheme.PARCHMENT)
			draw_rect(Rect2(at + Vector2(-14, -8), Vector2(28, 16)), ink, false, 1.2)
			draw_colored_polygon(PackedVector2Array([at + Vector2(-4, 8), at + Vector2(3, 8), at + Vector2(-6, 13)]), UITheme.PARCHMENT)
			for i in 3:
				var lift := sin(clock * 6.0 - i * 0.9) * 1.5
				draw_circle(at + Vector2(-7 + i * 7, lift), 1.8, ink)
		"alarmed":
			draw_circle(at, 9, Color("f3d27a"))
			draw_arc(at, 9, 0, TAU, 20, ink, 1.4, true)
			draw_rect(Rect2(at + Vector2(-1.4, -6), Vector2(2.8, 7.5)), ink)
			draw_circle(at + Vector2(0, 4.5), 1.5, ink)
		"hostile":
			var pulse := 1.0 + sin(clock * 5.0) * 0.08
			draw_circle(at, 10 * pulse, UITheme.STEAL)
			draw_arc(at, 10 * pulse, 0, TAU, 20, Color("3a0c06"), 1.4, true)
			for side in [-1.0, 1.0]:
				draw_line(at + Vector2(-5.5 * side, 5.5), at + Vector2(5.5 * side, -5.5), Color("fff0e0"), 2.2, true)
				draw_line(at + Vector2(-3.5 * side, 1.5), at + Vector2(-1.5 * side, 3.5), Color("fff0e0"), 2.0, true)
		"warm":
			var glow := 0.75 + sin(clock * 4.0) * 0.25
			for i in 8:
				var ray := Vector2.from_angle(i * TAU / 8.0)
				draw_line(at + ray * 7, at + ray * 11, Color(UITheme.GOLD, glow), 1.6, true)
			draw_circle(at, 6, Color(UITheme.GOLD, glow))
			draw_arc(at, 6, 0, TAU, 16, Color(UITheme.GOLD_DIM.darkened(0.3), glow), 1.2, true)
