extends RefCounted
## Cached geometry of an arbitrary held image. The image's painted grip is the hand socket's origin.

static var layouts := {}
static var standins := {}


static func fallback(profile: Dictionary, obj: Dictionary) -> Texture2D:
	var animation := str(profile.get("animation", "overhead"))
	var kind := str(obj.get("gear", {}).get("kind", "")) if typeof(obj.get("gear")) == TYPE_DICTIONARY else ""
	var key := animation + ":" + kind + ":" + str(profile.get("type", "blunt"))
	if standins.has(key):
		return standins[key]
	var drawing := '<line x1="18" y1="110" x2="102" y2="26" stroke="#785a37" stroke-width="8" stroke-linecap="round"/>'
	if kind == "shield":
		drawing = '<ellipse cx="64" cy="64" rx="43" ry="49" fill="#85643e" stroke="#bba581" stroke-width="5"/>' \
			+ '<circle cx="64" cy="64" r="12" fill="#807d70"/>'
	elif animation == "draw_shoot":
		drawing = '<path d="M22 112 Q-2 4 110 20" fill="none" stroke="#886440" stroke-width="7"/>' \
			+ '<line x1="22" y1="112" x2="110" y2="20" stroke="#d6c5a0" stroke-width="2"/>'
	elif animation == "pour":
		drawing = '<path d="M30 38 L90 38 L100 93 Q64 115 28 93 Z" fill="#8e6846" stroke="#c6a77b" stroke-width="4"/>'
	elif animation in ["spin", "spin_release", "lash"]:
		drawing = '<path d="M18 110 Q39 35 95 30 Q74 76 34 99" fill="none" stroke="#b2996e" stroke-width="5"/>' \
			+ '<ellipse cx="94" cy="30" rx="13" ry="9" fill="#786e5c"/>'
	elif animation in ["thrust", "two_hand_thrust", "stab"]:
		drawing += '<path d="M89 30 L117 11 L100 40 Z" fill="#aea995" stroke="#ded4b9" stroke-width="2"/>'
	elif animation in ["slash", "two_hand_swing"] and str(profile.get("type", "")) == "cut":
		drawing += '<path d="M41 80 L105 16 L116 10 L109 25 L49 88 Z" fill="#bcb8a8"/>'
	else:
		drawing += '<ellipse cx="98" cy="30" rx="17" ry="20" fill="#8f8879" stroke="#c6b691" stroke-width="3"/>'
	var picture := Image.new()
	picture.load_svg_from_string('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">' + drawing + '</svg>')
	var texture := ImageTexture.create_from_image(picture)
	var grip := Vector2(26, 102)
	if kind == "shield":
		grip = Vector2(64, 64)
	elif animation == "draw_shoot":
		grip = Vector2(32, 35) # On the painted bow, rather than in its empty middle.
	elif animation == "pour":
		grip = Vector2(30, 63)
	elif animation in ["spin", "spin_release", "lash"]:
		grip = Vector2(18, 110)
	var axis := Vector2(1, -1).normalized()
	texture.set_meta("held_layout", {"grip": grip, "support": grip + axis * 24,
		"axis": axis.angle(), "span": 120.0, "suitable": true})
	standins[key] = texture
	return texture


static func layout(texture: Texture2D, animation: String, kind: String) -> Dictionary:
	var key := str(texture.get_instance_id()) + ":" + animation + ":" + kind
	if layouts.has(key):
		return layouts[key]
	if texture.has_meta("held_layout"):
		layouts[key] = texture.get_meta("held_layout")
		return layouts[key]
	var picture := texture.get_image()
	var size := texture.get_size()
	var grip := size * .5
	var tip := Vector2(size.x * .9, size.y * .1)
	var axis := Vector2(1, -1).normalized()
	var span := size.length() * .8
	var suitable := false
	if picture != null:
		var sample: Image = picture.duplicate()
		sample.resize(64, 64, Image.INTERPOLATE_NEAREST)
		var low := INF
		var high := -INF
		var pixels: Array[Vector2] = []
		for y in 64:
			for x in 64:
				if sample.get_pixel(x, y).a > .45:
					var point := Vector2(x + .5, y + .5) * size / 64.0
					pixels.append(point)
					low = minf(low, point.dot(axis))
					high = maxf(high, point.dot(axis))
		suitable = pixels.size() > 4 and pixels.size() < 3900 and high - low > 12.0
		if suitable and kind != "shield":
			var wanted := low + (high - low) * .12
			grip = pixels[0]
			tip = pixels[0]
			for point in pixels:
				if absf(point.dot(axis) - wanted) < absf(grip.dot(axis) - wanted):
					grip = point
				if point.dot(axis) > tip.dot(axis):
					tip = point
			span = maxf(1.0, high - low)
			axis = (tip - grip).normalized()
	var result := {"grip": grip, "support": grip + axis * span * .20,
		"axis": axis.angle(), "span": span, "suitable": suitable}
	layouts[key] = result
	return result
