extends RefCounted
## The wood and parchment look (GDD D-35): palette, serif fonts, painted frames and cursors, all made
## in code at start-up (cached under user://ui_cache), so there is nothing to download or import.

const INK := Color("2e2014")
const INK_SOFT := Color("6a5238")
const ACCENT := Color("7c3a14") # Headings and names on parchment.
const THEIRS := Color("5b2410") # What other people say.
const GOOD := Color("365a22")
const BAD := Color("8f2a1c")
const STEAL := Color("c0392b")
const CREAM := Color("f3e6c8") # Text on wood.
const GOLD := Color("d9b36a")
const GOLD_DIM := Color("9c7d45")
const WOOD := Color("4c301b")
const WOOD_LIGHT := Color("70492a")
const WOOD_DARK := Color("22150c")
const PARCHMENT := Color("eee0bd")
const PARCHMENT_DARK := Color("d2bb8a")
const CACHE := "user://ui_cache/"
const VERSION := 4 # Bump to repaint the cached art.

static var _textures: Dictionary = {}
static var _cursors: Dictionary = {}


static var serif_fonts := {}


static func serif(bold := false, italic := false) -> SystemFont:
	var key := str(bold) + ":" + str(italic)
	if serif_fonts.has(key):
		return serif_fonts[key]
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Palatino Linotype", "Book Antiqua", "Palatino", "Georgia", "Serif"])
	font.font_weight = 700 if bold else 400
	font.font_italic = italic
	serif_fonts[key] = font
	return font


## One Theme for every Control under the UI root. text_scale multiplies all font sizes.
static func build(text_scale := 1.0) -> Theme:
	var theme := Theme.new()
	var regular := serif()
	var bold := serif(true)
	var size := func(base: int) -> int: return roundi(base * text_scale)
	theme.default_font = regular
	theme.default_font_size = size.call(17)
	theme.set_color("font_color", "Label", INK)
	theme.set_color("default_color", "RichTextLabel", INK)
	theme.set_font("bold_font", "RichTextLabel", bold)
	theme.set_font("italics_font", "RichTextLabel", serif(false, true))
	theme.set_font_size("normal_font_size", "RichTextLabel", size.call(16))
	theme.set_font_size("bold_font_size", "RichTextLabel", size.call(16))
	theme.set_font_size("italics_font_size", "RichTextLabel", size.call(16))
	for variation in ["WoodLabel", "Heading", "Caption", "Small", "Title"]:
		theme.set_type_variation(variation, "Label")
	theme.set_color("font_color", "WoodLabel", CREAM)
	theme.set_color("font_shadow_color", "WoodLabel", Color(0, 0, 0, 0.7))
	theme.set_constant("shadow_offset_y", "WoodLabel", 1)
	theme.set_font("font", "Heading", bold)
	theme.set_font_size("font_size", "Heading", size.call(23))
	theme.set_color("font_color", "Heading", ACCENT)
	theme.set_font("font", "Title", bold)
	theme.set_font_size("font_size", "Title", size.call(40))
	theme.set_color("font_color", "Title", ACCENT)
	theme.set_font("font", "Caption", bold)
	theme.set_font_size("font_size", "Caption", size.call(12))
	theme.set_color("font_color", "Caption", GOLD_DIM.darkened(0.25))
	theme.set_font_size("font_size", "Small", size.call(13))
	theme.set_color("font_color", "Small", INK_SOFT)

	theme.set_stylebox("panel", "PanelContainer", frame_box("frame_parchment", 18, 10))
	theme.set_stylebox("panel", "Panel", frame_box("frame_parchment", 18, 10))
	for variation in ["WoodPanel", "PaperPanel", "SlotPanel", "InsetPanel"]:
		theme.set_type_variation(variation, "PanelContainer")
	theme.set_stylebox("panel", "WoodPanel", frame_box("frame_wood", 18, 8))
	theme.set_stylebox("panel", "PaperPanel", frame_box("paper", 12, 6))
	var slot := flat(Color(0.10, 0.06, 0.03, 0.86), GOLD_DIM, 1, 5)
	slot.set_content_margin_all(3)
	slot.shadow_color = Color(0, 0, 0, 0.35)
	slot.shadow_size = 2
	theme.set_stylebox("panel", "SlotPanel", slot)
	var inset := flat(Color(0.93, 0.87, 0.72, 0.9), Color(0.55, 0.42, 0.25, 0.55), 1, 6)
	inset.set_content_margin_all(8)
	theme.set_stylebox("panel", "InsetPanel", inset)

	theme.set_stylebox("normal", "Button", plank_box("plank"))
	theme.set_stylebox("hover", "Button", plank_box("plank_hover"))
	theme.set_stylebox("pressed", "Button", plank_box("plank_pressed"))
	theme.set_stylebox("hover_pressed", "Button", plank_box("plank_pressed"))
	theme.set_stylebox("disabled", "Button", plank_box("plank"))
	theme.set_stylebox("focus", "Button", StyleBoxEmpty.new())
	theme.set_color("font_color", "Button", CREAM)
	theme.set_color("font_hover_color", "Button", GOLD)
	theme.set_color("font_pressed_color", "Button", GOLD)
	theme.set_color("font_hover_pressed_color", "Button", GOLD)
	theme.set_color("font_focus_color", "Button", CREAM)
	theme.set_color("font_disabled_color", "Button", Color(CREAM, 0.4))
	theme.set_font("font", "Button", bold)
	theme.set_font_size("font_size", "Button", size.call(15))
	# Chips and tabs: small parchment tokens (reference chips, participant tabs, journal tabs).
	theme.set_type_variation("Chip", "Button")
	var chip := flat(Color(0.87, 0.79, 0.60), Color(0.55, 0.42, 0.25, 0.8), 1, 11)
	chip.content_margin_left = 9
	chip.content_margin_right = 9
	chip.content_margin_top = 3
	chip.content_margin_bottom = 3
	var chip_hover := chip.duplicate()
	chip_hover.bg_color = Color(0.93, 0.86, 0.67)
	chip_hover.border_color = ACCENT
	var chip_on := chip.duplicate()
	chip_on.bg_color = Color(0.85, 0.68, 0.38)
	chip_on.border_color = ACCENT
	chip_on.set_border_width_all(2)
	theme.set_stylebox("normal", "Chip", chip)
	theme.set_stylebox("hover", "Chip", chip_hover)
	theme.set_stylebox("pressed", "Chip", chip_on)
	theme.set_stylebox("hover_pressed", "Chip", chip_on)
	theme.set_color("font_color", "Chip", INK)
	theme.set_color("font_hover_color", "Chip", ACCENT)
	theme.set_color("font_pressed_color", "Chip", INK)
	theme.set_color("font_hover_pressed_color", "Chip", INK)
	theme.set_color("font_focus_color", "Chip", INK)
	theme.set_font("font", "Chip", regular)
	theme.set_font_size("font_size", "Chip", size.call(14))
	theme.set_constant("icon_max_width", "Chip", 22)
	# Quiet text buttons: "×", "Details", links.
	theme.set_type_variation("Quiet", "Button")
	for state in ["normal", "hover", "pressed", "hover_pressed", "disabled"]:
		var empty := StyleBoxEmpty.new()
		empty.set_content_margin_all(2)
		theme.set_stylebox(state, "Quiet", empty)
	theme.set_color("font_color", "Quiet", INK_SOFT)
	theme.set_color("font_hover_color", "Quiet", ACCENT)
	theme.set_color("font_pressed_color", "Quiet", ACCENT)
	theme.set_color("font_focus_color", "Quiet", INK_SOFT)
	theme.set_font("font", "Quiet", bold)

	var field := flat(Color(0.98, 0.95, 0.86), Color(0.55, 0.42, 0.25, 0.9), 1, 5)
	field.content_margin_left = 10
	field.content_margin_right = 10
	field.content_margin_top = 6
	field.content_margin_bottom = 6
	var field_focus := field.duplicate()
	field_focus.border_color = ACCENT
	field_focus.set_border_width_all(2)
	for type in ["LineEdit", "TextEdit"]:
		theme.set_stylebox("normal", type, field)
		theme.set_stylebox("focus", type, field_focus)
		theme.set_stylebox("read_only", type, field)
		theme.set_color("font_color", type, INK)
		theme.set_color("font_readonly_color", type, INK_SOFT)
		theme.set_color("font_placeholder_color", type, Color(INK_SOFT, 0.7))
		theme.set_color("caret_color", type, ACCENT)
		theme.set_color("selection_color", type, Color(0.85, 0.68, 0.38, 0.6))
		theme.set_font_size("font_size", type, size.call(17))

	theme.set_stylebox("panel", "TooltipPanel", frame_box("paper", 12, 6))
	theme.set_color("font_color", "TooltipLabel", INK)
	theme.set_font_size("font_size", "TooltipLabel", size.call(14))

	var grabber := flat(Color(WOOD_LIGHT, 0.85), Color(0, 0, 0, 0), 0, 4)
	var grabber_hover := flat(GOLD_DIM, Color(0, 0, 0, 0), 0, 4)
	var track := flat(Color(0.45, 0.33, 0.18, 0.18), Color(0, 0, 0, 0), 0, 4)
	track.content_margin_left = 5
	track.content_margin_right = 5
	for type in ["VScrollBar", "HScrollBar"]:
		theme.set_stylebox("scroll", type, track)
		theme.set_stylebox("grabber", type, grabber)
		theme.set_stylebox("grabber_highlight", type, grabber_hover)
		theme.set_stylebox("grabber_pressed", type, grabber_hover)
	var slider := flat(Color(0.45, 0.33, 0.18, 0.35), Color(0, 0, 0, 0), 0, 3)
	slider.content_margin_top = 3
	slider.content_margin_bottom = 3
	theme.set_stylebox("slider", "HSlider", slider)
	theme.set_stylebox("grabber_area", "HSlider", flat(GOLD_DIM, Color(0, 0, 0, 0), 0, 3))
	theme.set_stylebox("grabber_area_highlight", "HSlider", flat(GOLD, Color(0, 0, 0, 0), 0, 3))
	var line := StyleBoxLine.new()
	line.color = Color(0.55, 0.42, 0.25, 0.45)
	line.thickness = 1
	theme.set_stylebox("separator", "HSeparator", line)
	theme.set_constant("separation", "HSeparator", 10)
	return theme


## A picture fitted into its space keeping its shape (icons, portraits, a dragged thing); at least size if given.
static func picture(art: Texture2D = null, size := Vector2.ZERO) -> TextureRect:
	var node := TextureRect.new()
	node.texture = art
	node.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	node.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	node.custom_minimum_size = size
	return node


static func flat(fill: Color, border: Color, width: int, radius: int) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = fill
	box.border_color = border
	box.set_border_width_all(width)
	box.set_corner_radius_all(radius)
	box.set_content_margin_all(6)
	return box


## A painted nine-patch frame: `margin` is the frame thickness, `pad` the extra room inside it.
static func frame_box(name: String, margin: int, pad: int) -> StyleBoxTexture:
	var box := StyleBoxTexture.new()
	box.texture = texture(name)
	box.texture_margin_left = margin
	box.texture_margin_right = margin
	box.texture_margin_top = margin
	box.texture_margin_bottom = margin
	box.set_content_margin_all(margin + pad - (6 if name == "paper" else 0))
	box.axis_stretch_horizontal = StyleBoxTexture.AXIS_STRETCH_MODE_TILE_FIT
	box.axis_stretch_vertical = StyleBoxTexture.AXIS_STRETCH_MODE_TILE_FIT
	return box


static func plank_box(name: String) -> StyleBoxTexture:
	var box := StyleBoxTexture.new()
	box.texture = texture(name)
	box.texture_margin_left = 8
	box.texture_margin_right = 8
	box.texture_margin_top = 8
	box.texture_margin_bottom = 8
	box.content_margin_left = 16
	box.content_margin_right = 16
	box.content_margin_top = 6
	box.content_margin_bottom = 7
	return box


## Painted art by name, from the cache or made now.
static func texture(name: String) -> Texture2D:
	if _textures.has(name):
		return _textures[name]
	var path := CACHE + "%s_v%d.png" % [name, VERSION]
	var image: Image = null
	if FileAccess.file_exists(path):
		image = Image.load_from_file(path)
	if image == null:
		image = _paint(name)
		DirAccess.make_dir_recursive_absolute(CACHE)
		image.save_png(path)
	_textures[name] = ImageTexture.create_from_image(image)
	return _textures[name]


static func _seamless(size: int, frequency: float, seed_value: int, octaves: int) -> Image:
	var noise := FastNoiseLite.new()
	noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	noise.seed = seed_value
	noise.frequency = frequency
	noise.fractal_octaves = octaves
	return noise.get_seamless_image(size, size)


static func _paint(name: String) -> Image:
	match name:
		"frame_parchment":
			return _frame(192, 18, true)
		"frame_wood":
			return _frame(192, 18, false)
		"paper":
			return _paper(128, 12)
		"map_paper":
			return _paper(256, 0)
		"plank", "plank_hover", "plank_pressed":
			return _plank(name)
	return Image.create_empty(4, 4, false, Image.FORMAT_RGBA8)


static func _wood_at(grain_value: float, speckle: float) -> Color:
	var ring := fposmod(grain_value * 11.0, 1.0)
	var band := smoothstep(0.0, 0.35, ring) * (1.0 - smoothstep(0.55, 1.0, ring))
	return WOOD.lerp(WOOD_LIGHT, band * 0.55 + grain_value * 0.25).darkened(speckle)


static func _paper_at(tone: float, speckle: float) -> Color:
	return PARCHMENT.lerp(PARCHMENT_DARK, clampf(tone * 0.9 - 0.15, 0.0, 1.0)).darkened(speckle)


## A dark wood frame with a gold bead and brass rivets around parchment (or dark wood) inside.
static func _frame(inner: int, margin: int, parchment: bool) -> Image:
	var edge := inner + margin * 2
	var image := Image.create_empty(edge, edge, false, Image.FORMAT_RGBA8)
	var grain := _seamless(inner, 0.018, 11, 3)
	var tone := _seamless(inner, 0.012, 23, 4)
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	for y in edge:
		for x in edge:
			var d := mini(mini(x, y), mini(edge - 1 - x, edge - 1 - y))
			var sample_x := posmod(x - margin, inner)
			var sample_y := posmod(y - margin, inner)
			var colour: Color
			if d < 2:
				colour = Color("120a05")
			elif d < margin - 7:
				# Grain runs along each side of the frame.
				var along := sample_x if (y < margin or y >= edge - margin) else sample_y
				var across := sample_y if (y < margin or y >= edge - margin) else sample_x
				var g := grain.get_pixel(along, (across * 5) % inner).r
				colour = _wood_at(g, rng.randf_range(0.0, 0.06))
				if d < 4:
					colour = colour.lightened(0.14)
				elif d >= margin - 9:
					colour = colour.darkened(0.3)
			elif d < margin - 5:
				colour = GOLD if d == margin - 7 else GOLD_DIM.darkened(0.2)
			else:
				# The inner shadow stays inside the border, so the tiled centre has no seams.
				var shade := maxf(0.0, float(margin - d)) * 0.05
				if parchment:
					colour = _paper_at(tone.get_pixel(sample_x, sample_y).r, rng.randf_range(0.0, 0.035) + shade)
				else:
					var g2 := grain.get_pixel(sample_x, (sample_y * 3) % inner).r
					colour = WOOD_DARK.lerp(WOOD, g2 * 0.35).darkened(rng.randf_range(0.0, 0.05) + shade)
					colour.a = 0.94
			image.set_pixel(x, y, colour)
	for corner in [Vector2(margin * 0.5, margin * 0.5), Vector2(edge - margin * 0.5, margin * 0.5),
			Vector2(margin * 0.5, edge - margin * 0.5), Vector2(edge - margin * 0.5, edge - margin * 0.5)]:
		_disc(image, corner, 3.2, GOLD_DIM.darkened(0.3))
		_disc(image, corner - Vector2(0.6, 0.6), 2.2, GOLD)
	return image


## Loose parchment with darkened, slightly ragged edges (tooltips, notices, cards, the map).
static func _paper(inner: int, margin: int) -> Image:
	var edge := inner + margin * 2
	var image := Image.create_empty(edge, edge, false, Image.FORMAT_RGBA8)
	var tone := _seamless(inner, 0.02, 31, 4)
	var rag := _seamless(inner, 0.08, 5, 2)
	var rng := RandomNumberGenerator.new()
	rng.seed = 9
	for y in edge:
		for x in edge:
			var d := mini(mini(x, y), mini(edge - 1 - x, edge - 1 - y))
			var sx := posmod(x - margin, inner)
			var sy := posmod(y - margin, inner)
			var colour := _paper_at(tone.get_pixel(sx, sy).r, rng.randf_range(0.0, 0.03))
			if margin > 0:
				var burn := clampf(1.0 - float(d) / float(margin), 0.0, 1.0)
				colour = colour.lerp(Color("a07e4a"), burn * burn * 0.8)
				if d < 3 and rag.get_pixel(sx, sy).r > 0.35 + d * 0.15:
					colour.a = 0.0
			image.set_pixel(x, y, colour)
	return image


static func _plank(name: String) -> Image:
	var w := 96
	var h := 40
	var image := Image.create_empty(w, h, false, Image.FORMAT_RGBA8)
	var grain := _seamless(96, 0.03, 17, 3)
	var pressed := name == "plank_pressed"
	var hover := name == "plank_hover"
	for y in h:
		for x in w:
			var corner := Vector2(clampf(x, 5, w - 6), clampf(y, 5, h - 6))
			if Vector2(x, y).distance_to(corner) > 5.2:
				image.set_pixel(x, y, Color(0, 0, 0, 0))
				continue
			var d := mini(mini(x, y), mini(w - 1 - x, h - 1 - y))
			var colour := _wood_at(grain.get_pixel(x, (y * 6) % 96).r, 0.0)
			if pressed:
				colour = colour.darkened(0.22)
			if d < 1 or Vector2(x, y).distance_to(corner) > 4.2:
				colour = Color("140b05")
			elif hover and d < 3:
				colour = GOLD
			elif d < 3:
				colour = colour.lightened(0.18) if (y < h / 2) != pressed else colour.darkened(0.3)
			image.set_pixel(x, y, colour)
	return image


static func _disc(image: Image, centre: Vector2, radius: float, colour: Color) -> void:
	for y in range(floori(centre.y - radius - 1), ceili(centre.y + radius + 1)):
		for x in range(floori(centre.x - radius - 1), ceili(centre.x + radius + 1)):
			if x < 0 or y < 0 or x >= image.get_width() or y >= image.get_height():
				continue
			var cover := clampf(radius + 0.5 - Vector2(x + 0.5, y + 0.5).distance_to(centre), 0.0, 1.0)
			if cover > 0.0:
				image.set_pixel(x, y, image.get_pixel(x, y).blend(Color(colour, colour.a * cover)))


# --- Cursors ---------------------------------------------------------------------------------------

const ARROW := [Vector2(2, 2), Vector2(2, 23), Vector2(7.5, 18), Vector2(11.5, 26.5), Vector2(15, 25),
	Vector2(11.2, 16.8), Vector2(18.5, 16.8)]


## A brass arrow, with a badge for what a click will do: talk, take, steal, use, look, far.
static func cursor(kind: String) -> Texture2D:
	if _cursors.has(kind):
		return _cursors[kind]
	var path := CACHE + "cursor_%s_v%d.png" % [kind, VERSION]
	var image: Image = null
	if FileAccess.file_exists(path):
		image = Image.load_from_file(path)
	if image == null:
		image = _paint_cursor(kind)
		DirAccess.make_dir_recursive_absolute(CACHE)
		image.save_png(path)
	_cursors[kind] = ImageTexture.create_from_image(image)
	return _cursors[kind]


static func _paint_cursor(kind: String) -> Image:
	var size := 32
	var image := Image.create_empty(size, size, false, Image.FORMAT_RGBA8)
	var far := kind == "far"
	for y in size:
		for x in size:
			var total := Color(0, 0, 0, 0)
			for sy in 4:
				for sx in 4:
					var p := Vector2(x + (sx + 0.5) / 4.0, y + (sy + 0.5) / 4.0)
					total += _cursor_sample(kind, p, far)
			image.set_pixel(x, y, total / 16.0)
	return image


static func _cursor_sample(kind: String, p: Vector2, far: bool) -> Color:
	var badge := Vector2(23.5, 23.5)
	if kind in ["talk", "take", "steal", "use", "look"]:
		var r := p.distance_to(badge)
		if kind == "talk":
			var bubble := Vector2((p.x - 23.0) / 8.5, (p.y - 21.5) / 6.5).length()
			var tail := Geometry2D.is_point_in_polygon(p, PackedVector2Array([Vector2(18, 25), Vector2(16, 31), Vector2(23, 27)]))
			if bubble <= 1.0 or tail:
				for dot in [Vector2(19.5, 21.5), Vector2(23, 21.5), Vector2(26.5, 21.5)]:
					if p.distance_to(dot) < 1.25:
						return INK
				return Color("fbf1d8") if bubble <= 0.82 or (tail and bubble > 1.0 and _in_shrunk_tail(p)) else INK
		elif r <= 8.5:
			var fill: Color = STEAL if kind == "steal" else Color("fbf1d8")
			var glyph: Color = Color("fff3e0") if kind == "steal" else INK
			if r > 7.2:
				return INK
			match kind:
				"take", "steal":
					if Geometry2D.is_point_in_polygon(p, PackedVector2Array([Vector2(19.5, 23), Vector2(27.5, 23), Vector2(23.5, 28)])) \
							or (absf(p.x - 23.5) < 1.3 and p.y > 18.0 and p.y < 24.0):
						return glyph
				"use":
					if absf(p.x - 23.5) + absf(p.y - 23.5) < 3.6:
						return Color(GOLD_DIM.darkened(0.2))
				"look":
					var lens := p.distance_to(Vector2(22.5, 22.5))
					if (lens > 2.6 and lens < 4.2) or (p.x > 24.5 and p.y > 24.5 and absf((p.x - 24.5) - (p.y - 24.5)) < 1.2 and p.x < 28.0):
						return glyph
			return fill
	var inside := Geometry2D.is_point_in_polygon(p, PackedVector2Array(ARROW))
	var distance := _polygon_distance(p, ARROW)
	if inside and distance > 1.3:
		var shade := clampf((p.y - 2.0) / 24.0, 0.0, 1.0)
		var body := Color("f0cf86").lerp(Color("8f6a32"), shade)
		if far:
			body = Color(0.62, 0.6, 0.56).lerp(Color(0.38, 0.36, 0.33), shade)
		return body
	if inside or distance <= 1.3:
		return Color("1b1109")
	if distance <= 2.4:
		return Color(0, 0, 0, 0.28) # A soft shadow so the arrow reads on bright grass.
	return Color(0, 0, 0, 0)


static func _in_shrunk_tail(p: Vector2) -> bool:
	return Geometry2D.is_point_in_polygon(p, PackedVector2Array([Vector2(19, 25.5), Vector2(17.6, 29.5), Vector2(22, 26.8)]))


static func _polygon_distance(p: Vector2, points: Array) -> float:
	var best := INF
	for i in points.size():
		var a: Vector2 = points[i]
		var b: Vector2 = points[(i + 1) % points.size()]
		best = minf(best, p.distance_to(Geometry2D.get_closest_point_to_segment(p, a, b)))
	return best
