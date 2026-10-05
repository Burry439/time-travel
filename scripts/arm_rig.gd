extends RefCounted
## Two painted limb segments and a hand socket. All points live in the view's original atlas coordinates.

const BODY_MASK := preload("res://scripts/arm_mask.gdshader")

# Shoulder, elbow, grip, half-width as fractions of the measured painted box. Anatomy, never weapon ids.
const TRAVELER := [
	{"right": [Vector2(.26,.25), Vector2(.105,.445), Vector2(.10,.555), .10],
		"left": [Vector2(.76,.28), Vector2(.87,.49), Vector2(.845,.60), .10]},
	{"right": [Vector2(.61,.28), Vector2(.70,.53), Vector2(.60,.63), .20],
		"left": [Vector2(.19,.28), Vector2(.13,.49), Vector2(.13,.61), .13]},
	{"right": [Vector2(.74,.27), Vector2(.87,.45), Vector2(.87,.57), .10],
		"left": [Vector2(.26,.27), Vector2(.12,.46), Vector2(.12,.58), .10]},
	{"right": [Vector2(.44,.29), Vector2(.23,.53), Vector2(.36,.625), .21],
		"left": [Vector2(.76,.29), Vector2(.83,.50), Vector2(.79,.60), .13]},
	{"right": [Vector2(.38,.27), Vector2(.26,.47), Vector2(.25,.59), .12],
		"left": [Vector2(.77,.27), Vector2(.87,.47), Vector2(.84,.59), .10]},
	{"right": [Vector2(.24,.27), Vector2(.12,.47), Vector2(.14,.59), .10],
		"left": [Vector2(.62,.27), Vector2(.73,.47), Vector2(.72,.59), .12]},
	{"right": [Vector2(.68,.27), Vector2(.80,.47), Vector2(.81,.59), .12],
		"left": [Vector2(.25,.27), Vector2(.12,.47), Vector2(.13,.59), .10]},
	{"right": [Vector2(.32,.27), Vector2(.20,.47), Vector2(.20,.59), .12],
		"left": [Vector2(.77,.27), Vector2(.88,.47), Vector2(.87,.59), .10]}
]

# Measured on each existing four-view painting: right/left shoulder, elbow, hand, sleeve half-width.
# Rows follow the renderer's facing order (front, left, back, right), not the atlas's cell order.
const VILLAGE := {
	"hessa": [
		[[.24,.25,.14,.42,.15,.57,.11], [.78,.26,.87,.43,.88,.57,.10]],
		[[.55,.27,.61,.46,.43,.60,.20], [.21,.29,.13,.47,.14,.61,.13]],
		[[.78,.27,.90,.43,.90,.56,.11], [.25,.27,.10,.43,.08,.56,.11]],
		[[.80,.27,.87,.46,.88,.59,.13], [.32,.27,.34,.46,.39,.61,.21]]],
	"roderic": [
		[[.21,.28,.08,.42,.08,.57,.11], [.77,.28,.80,.44,.77,.57,.11]],
		[[.48,.30,.43,.51,.37,.58,.21], [.16,.29,.08,.49,.08,.59,.13]],
		[[.78,.29,.91,.45,.93,.56,.10], [.25,.29,.10,.45,.10,.56,.10]],
		[[.81,.28,.88,.44,.85,.58,.13], [.42,.29,.50,.45,.59,.58,.21]]],
	"bren": [
		[[.20,.26,.10,.44,.12,.58,.11], [.77,.26,.90,.44,.88,.57,.11]],
		[[.60,.27,.68,.48,.57,.60,.23], [.21,.26,.11,.47,.15,.60,.13]],
		[[.77,.27,.90,.47,.90,.57,.11], [.22,.27,.08,.47,.09,.57,.11]],
		[[.82,.28,.84,.46,.85,.61,.13], [.30,.28,.20,.46,.27,.59,.23]]],
	"oren": [
		[[.20,.27,.13,.44,.10,.57,.11], [.80,.27,.89,.43,.88,.56,.11]],
		[[.70,.28,.74,.46,.46,.60,.25], [.24,.28,.16,.47,.16,.60,.13]],
		[[.78,.27,.88,.45,.87,.58,.11], [.21,.27,.11,.45,.11,.58,.11]],
		[[.85,.28,.87,.46,.92,.60,.13], [.25,.28,.26,.47,.48,.58,.25]]],
	"mara": [
		[[.18,.28,.10,.44,.10,.59,.11], [.78,.27,.86,.46,.91,.58,.11]],
		[[.60,.29,.72,.49,.52,.63,.22], [.13,.28,.12,.48,.12,.61,.13]],
		[[.78,.28,.91,.45,.92,.57,.11], [.23,.28,.10,.45,.08,.57,.11]],
		[[.82,.28,.82,.50,.80,.60,.13], [.27,.29,.29,.50,.40,.63,.22]]],
	"jory": [
		[[.23,.29,.14,.43,.09,.59,.11], [.80,.28,.87,.46,.91,.58,.11]],
		[[.68,.29,.68,.48,.48,.62,.24], [.14,.29,.10,.48,.10,.60,.13]],
		[[.80,.29,.89,.44,.91,.57,.11], [.21,.29,.13,.44,.10,.58,.11]],
		[[.85,.28,.87,.46,.90,.62,.13], [.30,.30,.30,.46,.44,.60,.24]]],
	"tomas": [
		[[.25,.26,.15,.43,.17,.57,.11], [.77,.27,.88,.42,.91,.55,.11]],
		[[.67,.27,.66,.48,.50,.59,.23], [.16,.29,.10,.46,.12,.60,.13]],
		[[.80,.28,.90,.45,.94,.57,.11], [.21,.28,.08,.45,.06,.57,.11]],
		[[.83,.28,.88,.44,.92,.58,.13], [.29,.28,.32,.43,.43,.58,.23]]],
	"darin": [
		[[.23,.27,.13,.46,.13,.57,.11], [.77,.27,.90,.45,.91,.55,.11]],
		[[.62,.29,.59,.49,.47,.59,.23], [.16,.29,.11,.48,.12,.60,.13]],
		[[.80,.28,.90,.47,.92,.58,.11], [.24,.28,.10,.47,.09,.58,.11]],
		[[.83,.28,.86,.47,.89,.60,.13], [.30,.29,.38,.49,.49,.59,.23]]],
	"elin": [
		[[.21,.27,.11,.44,.08,.57,.12], [.81,.27,.90,.44,.91,.57,.12]],
		[[.62,.27,.68,.49,.47,.59,.26], [.18,.27,.11,.48,.11,.60,.13]],
		[[.81,.27,.91,.48,.92,.58,.12], [.21,.27,.09,.48,.08,.58,.12]],
		[[.85,.27,.88,.47,.92,.60,.13], [.31,.27,.35,.47,.49,.59,.26]]],
	"kade": [
		[[.21,.26,.11,.44,.11,.56,.12], [.79,.26,.91,.44,.90,.56,.12]],
		[[.64,.28,.64,.48,.44,.59,.25], [.18,.28,.10,.48,.12,.61,.13]],
		[[.80,.27,.91,.46,.93,.58,.12], [.22,.27,.09,.46,.10,.58,.12]],
		[[.86,.27,.89,.48,.91,.61,.13], [.28,.28,.28,.48,.41,.58,.25]]]
}


static func anchors(id: String, row: int, hand: String) -> Array:
	if id == "traveler":
		return TRAVELER[clampi(row, 0, 7)][hand].duplicate()
	# New characters get normalized anatomy compatible with the existing stand-in painting.
	var points: Array = VILLAGE.get(id, VILLAGE.tomas)[clampi(row, 0, 3)][0 if hand == "right" else 1]
	return [Vector2(points[0], points[1]), Vector2(points[2], points[3]), Vector2(points[4], points[5]), points[6]]


static func install(root: Node2D, atlas: Texture2D, box: Rect2i, points: Array) -> Dictionary:
	var origin := Vector2(box.position)
	var size := Vector2(box.size)
	var shoulder: Vector2 = origin + points[0] * size
	var elbow: Vector2 = origin + points[1] * size
	var wrist: Vector2 = origin + points[2] * size
	var width: float = points[3] * size.x
	var forearm := Node2D.new()
	forearm.name = "Forearm"
	forearm.position = elbow - shoulder
	root.add_child(forearm)
	var socket := Node2D.new()
	socket.name = "Hand"
	socket.position = wrist - elbow
	forearm.add_child(socket)
	_segment(root, atlas, shoulder, elbow, width, shoulder, 0.9)
	_segment(forearm, atlas, elbow, wrist, width * .73, elbow, 0.72)
	return {"root": root, "forearm": forearm, "socket": socket, "shoulder": shoulder,
		"elbow": elbow, "wrist": wrist, "upper": elbow - shoulder, "lower": wrist - elbow,
		"bend": signf((elbow - shoulder).cross(wrist - elbow)) if absf((elbow - shoulder).cross(wrist - elbow)) > 1.0 else 1.0}


static func _segment(parent: Node2D, atlas: Texture2D, from: Vector2, to: Vector2,
		width: float, pivot: Vector2, taper: float) -> void:
	var along := (to - from).normalized()
	var normal := along.orthogonal()
	var corners := PackedVector2Array([from - along * width * .35 + normal * width,
		from - along * width * .35 - normal * width, to + along * width * .55 - normal * width * taper,
		to + along * width * .55 + normal * width * taper])
	var piece := Polygon2D.new()
	piece.name = "Art"
	piece.texture = atlas
	piece.uv = corners
	var local := PackedVector2Array()
	for point in corners:
		local.append(point - pivot)
	piece.polygon = local
	piece.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	parent.add_child(piece)


static func solve(info: Dictionary, target: Vector2) -> void:
	var root: Node2D = info.root
	var upper: Vector2 = info.upper
	var lower: Vector2 = info.lower
	var distance := clampf(target.length(), absf(upper.length() - lower.length()) + .01, upper.length() + lower.length() - .01)
	var cosine := clampf((upper.length_squared() + distance * distance - lower.length_squared())
		/ (2.0 * upper.length() * distance), -1.0, 1.0)
	var angle := target.angle() - float(info.bend) * acos(cosine)
	var elbow := Vector2.from_angle(angle) * upper.length()
	var end := target.normalized() * distance
	root.rotation = angle - upper.angle()
	(info.forearm as Node2D).rotation = (end - elbow).angle() - angle - (lower.angle() - upper.angle())


static func constrain(info: Dictionary, target: Vector2) -> Vector2:
	var shoulder: Vector2 = (info.root as Node2D).position
	var upper: float = (info.upper as Vector2).length()
	var lower: float = (info.lower as Vector2).length()
	var toward := target - shoulder
	return shoulder + toward.normalized() * clampf(toward.length(), absf(upper - lower) + .02, upper + lower - .02)


static func body_mask(atlas: Texture2D, right: Dictionary, left: Dictionary, box: Rect2i, fill: bool) -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = BODY_MASK
	material.set_shader_parameter("atlas_size", atlas.get_size())
	material.set_shader_parameter("right_a", right.shoulder)
	material.set_shader_parameter("right_b", right.elbow)
	material.set_shader_parameter("right_c", right.wrist)
	material.set_shader_parameter("left_a", left.shoulder)
	material.set_shader_parameter("left_b", left.elbow)
	material.set_shader_parameter("left_c", left.wrist)
	material.set_shader_parameter("width", float(box.size.x) * (.08 if box.size.x > box.size.y * .35 else .17))
	material.set_shader_parameter("fill_body", fill)
	material.set_shader_parameter("body_x", float(box.position.x) + float(box.size.x) * .5)
	return material
