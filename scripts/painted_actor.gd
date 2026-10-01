@tool
extends Node2D
## Editor-visible cutout rig. Every layer samples the original painted atlas;
## no generated pixels are modified or re-exported.

const TRAVELER := preload("res://assets/generated/traveler_painted_turnaround.png")
const TRAVELER_DIAGONALS := preload("res://assets/generated/traveler_painted_diagonals.png")
const HESSA := preload("res://assets/generated/hessa_painted_turnaround.png")
const CAST_ART := {
	"roderic": preload("res://assets/generated/roderic_painted_turnaround.png"),
	"bren": preload("res://assets/generated/bren_painted_turnaround.png"),
	"oren": preload("res://assets/generated/oren_painted_turnaround.png"),
	"mara": preload("res://assets/generated/mara_painted_turnaround.png"),
	"jory": preload("res://assets/generated/jory_painted_turnaround.png"),
	"tomas": preload("res://assets/generated/tomas_painted_turnaround.png"),
	"darin": preload("res://assets/generated/darin_painted_turnaround.png"),
	"elin": preload("res://assets/generated/elin_painted_turnaround.png"),
	"kade": preload("res://assets/generated/kade_painted_turnaround.png")
}

## Whose painting: the traveler, or a person's name in lower case (the village's people are below; anyone else is
## assets/people/<name>.png, D-59).
@export var actor_id := "traveler":
	set(value):
		actor_id = value
		if is_inside_tree():
			_build()

@export_range(80.0, 140.0, 1.0) var height_px := 108.0:
	set(value):
		height_px = value
		if is_inside_tree():
			_build()

const CombatPose := preload("res://scripts/combat_pose.gd")
const PX_PER_METRE := 62.0 # The rig is about 1.75 m tall at 108 px.
# Where worn things sit, as fractions of a view's painted box: (x, y, width, height).
# A worn thing is fitted to the width of its part and hangs from the top of it (a mail shirt falls to the knee,
# a helmet sits on the crown), so its own proportions decide how far down it reaches.
const WORN_RECTS := {"head": Rect2(0.23, -0.06, 0.54, 0.3), "body": Rect2(0.13, 0.17, 0.74, 0.6),
	"legs": Rect2(0.12, 0.55, 0.76, 0.42), "feet": Rect2(0.1, 0.86, 0.8, 0.14)}
const WORN_PART := {"head": "head", "body": "torso", "legs": "hip_bridge", "feet": "hip_bridge"}
const WORN_ORDER := ["legs", "feet", "body", "head"] # Drawn in this order (a coat over leggings).

var views: Array[Node2D] = []
var joints: Array[Dictionary] = []
var rest_positions: Array[Dictionary] = []
var boxes: Array[Rect2i] = [] # Each view's painted box in its atlas.
var joint_px: Array[Dictionary] = [] # Each part's pivot, in atlas pixels.
var hand_points: Array[Dictionary] = [] # Where each hand is, in its arm pivot's space.
# What they hold and wear (D-49): hand -> {texture, animation, hands, kind, length_px}; slot -> [4 textures].
var held := {}
var worn := {}
var held_nodes: Array[Dictionary] = []
var attack := {} # {hand, animation, windup, t}
var guarding := false
var guard_hand := "left"
var facing := 0
var locomotion := "idle"
var stride_phase := 0.0
var pose_clock := 0.0
var gesture_time := 0.0
var gesture_kind := ""
var dead := false

const BOUNDS := {
	"traveler": [Rect2i(222, 49, 258, 573), Rect2i(831, 58, 151, 562),
		Rect2i(223, 647, 255, 541), Rect2i(835, 650, 138, 548)],
	"hessa": [Rect2i(174, 43, 305, 588), Rect2i(785, 59, 250, 578),
		Rect2i(181, 681, 299, 568), Rect2i(785, 685, 241, 571)],
	"roderic": [Rect2i(192,31,299,589), Rect2i(771,36,229,586), Rect2i(172,660,303,593), Rect2i(805,660,231,600)],
	"bren": [Rect2i(195,32,284,605), Rect2i(786,35,191,604), Rect2i(208,662,274,592), Rect2i(816,664,172,600)],
	"oren": [Rect2i(212,36,269,597), Rect2i(830,42,155,600), Rect2i(215,665,274,586), Rect2i(850,670,147,591)],
	"mara": [Rect2i(196,33,293,611), Rect2i(809,46,203,601), Rect2i(180,662,297,584), Rect2i(822,672,191,587)],
	"jory": [Rect2i(201,31,257,616), Rect2i(814,38,159,610), Rect2i(210,664,259,605), Rect2i(826,673,144,596)],
	"tomas": [Rect2i(196,28,285,600), Rect2i(801,31,198,604), Rect2i(202,661,290,588), Rect2i(814,661,191,604)],
	"darin": [Rect2i(199,41,270,591), Rect2i(804,42,183,592), Rect2i(198,668,291,575), Rect2i(820,668,182,590)],
	"elin": [Rect2i(236,33,241,605), Rect2i(824,37,148,607), Rect2i(240,672,236,581), Rect2i(838,675,150,593)],
	"kade": [Rect2i(189,31,292,612), Rect2i(819,31,181,613), Rect2i(191,660,292,601), Rect2i(817,661,166,613)]
}
const DIAGONAL_BOUNDS := [
	Rect2i(225, 47, 256, 582),  # southeast: front and right side
	Rect2i(794, 53, 237, 576),  # southwest: front and left side
	Rect2i(246, 635, 234, 568), # northwest: back and left side
	Rect2i(783, 636, 243, 564)  # northeast: back and right side
]
# The painted NPC atlases put right-facing at the top right; the traveler differs.
const TRAVELER_ORDER := [0, 1, 2, 3]
const CAST_ORDER := [0, 3, 2, 1]
const GAIT_LENGTH := {
	"traveler": 1.0, "hessa": 0.94, "roderic": 1.12, "bren": 1.03,
	"oren": 1.07, "mara": 0.96, "jory": 0.89, "tomas": 1.08,
	"darin": 1.04, "elin": 0.91, "kade": 1.06
}


func _ready() -> void:
	pose_clock = fposmod(float(actor_id.hash() % 628) / 100.0, TAU)
	stride_phase = pose_clock
	_build()
	set_motion(0, "idle", 0.0, 0.0)


const PEOPLE_DIR := "res://assets/people/"
const STAND_IN := "tomas" # Drawn for anyone whose painting isn't made yet, so a level plays before its art exists.
static var _sheets := {}


## Someone's painted sheet: {texture, views (the painted box of each view on it), order (which box faces which
## way), gait}. The traveler and the village's people are measured above; anyone else painted for a level is
## assets/people/<name>.png with <name>.json beside it, written by tools/make_person.py (D-59).
static func sheet_for(id: String) -> Dictionary:
	if _sheets.has(id):
		return _sheets[id]
	var sheet := {}
	if id == "traveler":
		sheet = {"texture": TRAVELER, "views": BOUNDS[id], "order": TRAVELER_ORDER, "gait": GAIT_LENGTH[id]}
	elif id == "hessa" or CAST_ART.has(id):
		sheet = {"texture": HESSA if id == "hessa" else CAST_ART[id], "views": BOUNDS[id], "order": CAST_ORDER,
			"gait": GAIT_LENGTH[id]}
	elif ResourceLoader.exists(PEOPLE_DIR + id + ".png") and FileAccess.file_exists(PEOPLE_DIR + id + ".json"):
		var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(PEOPLE_DIR + id + ".json"))
		var views: Array[Rect2i] = []
		for box in spec.views:
			views.append(Rect2i(int(box[0]), int(box[1]), int(box[2]), int(box[3])))
		sheet = {"texture": load(PEOPLE_DIR + id + ".png"), "views": views, "order": spec.get("order", CAST_ORDER),
			"gait": float(spec.get("gait", 1.0))}
	else:
		sheet = sheet_for(STAND_IN)
	_sheets[id] = sheet
	return sheet


func _build() -> void:
	for child in get_children():
		remove_child(child)
		child.queue_free()
	views.clear()
	joints.clear()
	rest_positions.clear()
	boxes.clear()
	joint_px.clear()
	hand_points.clear()
	held_nodes.clear()
	var view_count := 8 if actor_id == "traveler" else 4
	var sheet := sheet_for(actor_id)
	for row in view_count:
		var atlas: Texture2D = TRAVELER_DIAGONALS if row >= 4 else sheet.texture
		var box: Rect2i = DIAGONAL_BOUNDS[row - 4] if row >= 4 else sheet.views[sheet.order[row]]
		var whole := Node2D.new()
		whole.name = ["Front", "Left", "Back", "Right", "Southeast", "Southwest", "Northwest", "Northeast"][row]
		whole.visible = row == facing
		add_child(whole)
		views.append(whole)
		var center := Vector2(box.position.x + box.size.x * 0.5, box.end.y)
		var rig_scale := height_px / float(box.size.y)
		whole.scale = Vector2.ONE * rig_scale
		var rig: Dictionary = {}
		var rests: Dictionary = {}
		var pivots_px: Dictionary = {}
		var hands: Dictionary = {}
		boxes.append(box)
		# Overlaps are intentional, keeping painted seams hidden at the rest pose.
		# Anatomy differs by view; each part has its own shoulder/hip pivot.
		var slices := {
			"hip_bridge": Rect2(0.34, 0.53, 0.32, 0.34),
			"left_leg": Rect2(0.06, 0.57, 0.47, 0.43),
			"right_leg": Rect2(0.47, 0.57, 0.47, 0.43),
			"torso": Rect2(0.15, 0.19, 0.70, 0.51),
			"left_arm": Rect2(0.00, 0.22, 0.28, 0.46),
			"right_arm": Rect2(0.72, 0.22, 0.28, 0.46),
			"head": Rect2(0.18, 0.00, 0.64, 0.27)
		}
		for part_name in ["hip_bridge", "left_leg", "right_leg", "torso", "left_arm", "right_arm", "head"]:
			var area: Rect2 = slices[part_name]
			var region := Rect2i(
				box.position.x + roundi(box.size.x * area.position.x),
				box.position.y + roundi(box.size.y * area.position.y),
				ceili(box.size.x * area.size.x),
				ceili(box.size.y * area.size.y))
			var pivot := Node2D.new()
			pivot.name = part_name.to_pascal_case()
			var joint: Vector2 = Vector2(region.position)
			if part_name == "hip_bridge":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.1)
			elif part_name == "left_leg" or part_name == "right_leg":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.05)
			elif part_name == "head":
				joint += Vector2(region.size.x * 0.5, region.size.y * 0.85)
			else:
				joint += Vector2(region.size.x * (0.82 if part_name == "left_arm" else 0.18 if part_name == "right_arm" else 0.5), region.size.y * 0.12)
			pivot.position = joint - center
			whole.add_child(pivot)
			var section := Sprite2D.new()
			section.name = "Art"
			var texture := AtlasTexture.new()
			texture.atlas = atlas
			texture.region = Rect2(region)
			section.texture = texture
			section.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
			section.position = Vector2(region.position) + Vector2(region.size) * 0.5 - joint
			pivot.add_child(section)
			rig[part_name] = pivot
			rests[part_name] = pivot.position
			pivots_px[part_name] = joint
			if part_name == "left_arm" or part_name == "right_arm":
				hands[part_name] = Vector2(region.position) + Vector2(region.size.x * 0.5, region.size.y * 0.9) - joint
		joints.append(rig)
		rest_positions.append(rests)
		joint_px.append(pivots_px)
		hand_points.append(hands)
	_apply_gear()
	queue_redraw()


## What they hold (hand -> {texture, animation, hands, kind, length_m}) and wear (slot -> the 2x2 worn sheet
## as an Image). Rebuilt only when it changes.
func set_gear(new_held: Dictionary, new_worn: Dictionary) -> void:
	var worn_key := {}
	for slot in new_worn:
		worn_key[slot] = new_worn[slot].get_instance_id() if new_worn[slot] else 0
	var held_key := {}
	for hand in new_held:
		var texture: Texture2D = new_held[hand].get("texture")
		# Instance ids, never the texture itself: var_to_str() of a texture writes out every pixel (a 1024 px
		# held picture took ~0.7 s on every world update, D-51).
		held_key[hand] = [texture.get_instance_id() if texture else 0, new_held[hand].get("animation"),
			new_held[hand].get("kind")]
	var keys := str(held_key) + "|" + str(worn_key)
	if keys == str(get_meta("gear_key", "")):
		return
	set_meta("gear_key", keys)
	held = new_held
	worn = {}
	for slot in new_worn:
		if new_worn[slot]:
			worn[slot] = _slice_sheet(new_worn[slot])
	_apply_gear()


## A worn sheet is four views in a 2x2 grid: front, right side / back, left side.
func _slice_sheet(image: Image) -> Array:
	if image.is_compressed():
		image.decompress()
	var half := Vector2i(image.get_width() / 2, image.get_height() / 2)
	var quads := []
	for cell in [Vector2i(0, 0), Vector2i(1, 0), Vector2i(0, 1), Vector2i(1, 1)]:
		var part := image.get_region(Rect2i(cell * half, half))
		var used := solid_rect(part)
		quads.append(ImageTexture.create_from_image(part.get_region(used)) if used.size.x > 2 else null)
	return quads # [front, facing left, back, facing right]


## The box around what is really there: generated pictures can carry a faint haze that get_used_rect counts.
## Scans a small copy, so it stays quick.
static func solid_rect(image: Image, threshold := 0.35) -> Rect2i:
	var probe: Image = image.duplicate()
	var step := maxi(1, maxi(image.get_width(), image.get_height()) / 128)
	probe.resize(maxi(1, image.get_width() / step), maxi(1, image.get_height() / step), Image.INTERPOLATE_NEAREST)
	var low := Vector2i(probe.get_width(), probe.get_height())
	var high := Vector2i(-1, -1)
	for y in probe.get_height():
		for x in probe.get_width():
			if probe.get_pixel(x, y).a > threshold:
				low = Vector2i(mini(low.x, x), mini(low.y, y))
				high = Vector2i(maxi(high.x, x), maxi(high.y, y))
	if high.x < 0:
		return Rect2i()
	return Rect2i(low * step, (high - low + Vector2i.ONE) * step).intersection(Rect2i(Vector2i.ZERO, image.get_size()))


func _apply_gear() -> void:
	held_nodes.clear()
	for row in views.size():
		var rig: Dictionary = joints[row]
		for part_name in rig:
			for child in rig[part_name].get_children():
				if child.has_meta("gear"):
					rig[part_name].remove_child(child)
					child.queue_free()
		var box: Rect2i = boxes[row]
		# Worn layers, each view from the matching side of its sheet (diagonals use the front or back).
		var quadrant: int = [0, 1, 2, 3, 0, 0, 2, 2][row] # Sheet: front, facing left / back, facing right.
		for slot in WORN_ORDER:
			if not worn.has(slot) or worn[slot][quadrant] == null:
				continue
			var texture: Texture2D = worn[slot][quadrant]
			var area: Rect2 = WORN_RECTS[slot]
			var rect := Rect2(Vector2(box.position) + area.position * Vector2(box.size), area.size * Vector2(box.size))
			var layer := Sprite2D.new()
			layer.set_meta("gear", true)
			layer.texture = texture
			var fit := rect.size.x / texture.get_size().x
			if row in [1, 3]: # In profile a body is narrower than it is from the front.
				fit = minf(fit, rect.size.y / texture.get_size().y)
			layer.scale = Vector2.ONE * fit
			var part_name: String = WORN_PART[slot]
			var top_centre := Vector2(rect.get_center().x, rect.position.y + texture.get_size().y * fit * 0.5)
			layer.position = top_centre - joint_px[row][part_name]
			layer.z_index = 1
			rig[part_name].add_child(layer)
		# Held things hang from the hands: behind the body when facing away, mirrored when facing left.
		var nodes := {}
		for hand in held:
			var spec: Dictionary = held[hand]
			if spec.get("texture") == null:
				continue
			var arm := "right_arm" if hand == "right" else "left_arm"
			var sprite := Sprite2D.new()
			sprite.set_meta("gear", true)
			sprite.texture = spec.texture
			var size: Vector2 = spec.texture.get_size()
			var shield := str(spec.get("kind", "")) == "shield"
			var grip := Vector2.ZERO if shield else Vector2(-size.x * 0.4, size.y * 0.4)
			sprite.offset = -grip
			var length_px := maxf(18.0, float(spec.get("length_m", 0.4)) * PX_PER_METRE) if not shield else 34.0
			var span := size.length() if not shield else maxf(size.x, size.y)
			var rig_scale: float = views[row].scale.x
			sprite.scale = Vector2.ONE * (length_px / maxf(span, 1.0)) / maxf(rig_scale, 0.001)
			sprite.position = hand_points[row].get(arm, Vector2.ZERO)
			var away := row == 2 or row == 6 or row == 7
			sprite.z_index = -1 if away else 2
			if row == 1 or row == 5 or row == 6:
				sprite.scale.x *= -1.0
			rig[arm].add_child(sprite)
			nodes[hand] = sprite
		held_nodes.append(nodes)


## Start a blow with whatever is in that hand, its wind-up stretched over windup_ms so it can be read.
func play_attack(animation: String, windup_ms: float, hand := "right") -> void:
	if dead:
		return
	attack = {"hand": hand, "animation": animation, "windup": maxf(0.05, windup_ms / 1000.0), "t": 0.0}


func set_guard(raised: bool, hand := "left") -> void:
	guarding = raised
	guard_hand = hand


func set_motion(row: int, mode: String, distance: float, delta: float) -> void:
	if views.is_empty() or dead:
		return
	facing = clampi(row, 0, views.size() - 1)
	locomotion = mode
	pose_clock += delta
	if mode == "walk" or mode == "run":
		stride_phase += distance * TAU / ((96.0 if mode == "walk" else 118.0) * float(sheet_for(actor_id).gait))
	for i in views.size():
		views[i].visible = i == facing
	var rig: Dictionary = joints[facing]
	var active := mode == "walk" or mode == "run"
	var leg_swing := sin(stride_phase) * (0.10 if mode == "walk" else 0.15) if active else 0.0
	if actor_id == "hessa":
		leg_swing *= 0.48
	var sway := sin(pose_clock * 1.5) * 0.012
	var gesture := 0.0
	if gesture_time > 0.0:
		gesture_time = maxf(0.0, gesture_time - delta)
		gesture = sin((1.0 - gesture_time / 0.48) * PI) * 0.24
		if gesture_kind == "pickup":
			gesture *= -1.0
	for part_name in rig:
		var pivot: Node2D = rig[part_name]
		pivot.rotation = 0.0
		pivot.scale = Vector2.ONE
		pivot.position = rest_positions[facing][part_name]
	if active:
		if facing == 1 or facing == 3:
			var forward := -1.0 if facing == 1 else 1.0
			var swing := cos(stride_phase) * (0.20 if mode == "run" else 0.15)
			rig["left_leg"].rotation = swing * forward
			rig["right_leg"].rotation = -swing * forward
		else:
			rig["left_leg"].rotation = leg_swing
			rig["right_leg"].rotation = -leg_swing
			var depth := sin(stride_phase) * (5.0 if mode == "run" else 3.0) / views[facing].scale.y
			rig["left_leg"].position.y += depth
			rig["right_leg"].position.y -= depth
		rig["left_arm"].rotation = -leg_swing * 0.55
		rig["right_arm"].rotation = leg_swing * 0.55
	rig["head"].rotation = sway * 0.45
	rig["torso"].rotation = sway
	if mode == "work":
		rig["left_arm"].rotation = sin(pose_clock * 6.0) * 0.13
		rig["right_arm"].rotation = -sin(pose_clock * 6.0) * 0.21
		rig["torso"].rotation += sin(pose_clock * 6.0) * 0.018
	elif mode == "look" or mode == "patrol":
		rig["head"].rotation += sin(pose_clock * 1.15) * 0.055
	elif mode == "conversation":
		rig["right_arm"].rotation = sin(pose_clock * 3.0) * 0.16
	rig["right_arm"].rotation += gesture
	var bob := absf(sin(stride_phase)) * (0.9 if mode == "walk" else 1.8) if active else sin(pose_clock * 1.5) * 0.25
	for part_name in ["head", "left_arm", "right_arm", "torso"]:
		var pivot: Node2D = rig[part_name]
		pivot.position.y = (rest_positions[facing][part_name] as Vector2).y - bob / views[facing].scale.y
	if gesture_time > 0.0 and gesture_kind == "pickup":
		for part_name in ["head", "left_arm", "right_arm", "torso"]:
			var pivot: Node2D = rig[part_name]
			pivot.position.y += gesture * 10.0
	_pose_fighting(rig, delta)


## Blows, guarding and how held things sit (D-49), on top of walking and idling.
func _pose_fighting(rig: Dictionary, delta: float) -> void:
	# Forward is +x on right-facing views; a positive arm angle swings the hand forward.
	var forward := -1.0 if facing in [1, 5, 6] else 1.0
	var nodes: Dictionary = held_nodes[facing] if facing < held_nodes.size() else {}
	for hand in nodes:
		var sprite: Sprite2D = nodes[hand]
		var spec: Dictionary = held.get(hand, {})
		var shield := str(spec.get("kind", "")) == "shield"
		var carry := 0.0 if shield else CombatPose.hold_angle(str(spec.get("animation", "slash")))
		if facing == 0 or facing == 2:
			carry -= PI / 4.0 # Front and back views: held upright at the side.
		sprite.rotation = carry * (1.0 if sprite.scale.x > 0 else -1.0)
		sprite.position = hand_points[facing].get("right_arm" if hand == "right" else "left_arm", Vector2.ZERO)
	if guarding:
		var arm := "left_arm" if guard_hand == "left" else "right_arm"
		rig[arm].rotation = -1.25 * forward
		rig["torso"].rotation += 0.03 * forward
	if attack.is_empty():
		return
	attack.t += delta
	var windup: float = attack.windup
	var animation: String = attack.animation
	if attack.t > CombatPose.duration(windup):
		attack = {}
		return
	var angle := CombatPose.arm_angle(animation, attack.t, windup)
	var striking := "right_arm" if attack.hand == "right" else "left_arm"
	rig[striking].rotation = -angle * forward
	if CombatPose.both_arms(animation):
		var other := "left_arm" if striking == "right_arm" else "right_arm"
		rig[other].rotation = -angle * forward * 0.85
	rig["torso"].rotation += CombatPose.torso_lean(animation, attack.t, windup) * forward
	var sprite: Sprite2D = nodes.get(attack.hand)
	if sprite:
		# Thrusts, stabs and shots point the weapon straight where they face; swings carry it round with the arm.
		var aimed := animation in ["thrust", "two_hand_thrust", "stab", "draw_shoot", "bash"]
		var arm_turn: float = rig[striking].rotation
		var target := 0.0 if forward > 0 else PI
		if facing == 0:
			target = PI / 2.0
		elif facing == 2:
			target = -PI / 2.0
		var painted_axis := -PI / 4.0 if sprite.scale.x > 0 else -3.0 * PI / 4.0
		if aimed:
			sprite.rotation = target - arm_turn - painted_axis
		var along := Vector2.from_angle((target if aimed else arm_turn + sprite.rotation + painted_axis) - arm_turn)
		sprite.position += along * CombatPose.reach(animation, attack.t, windup) / maxf(views[facing].scale.x, 0.001)


func play_gesture(kind: String) -> void:
	gesture_kind = kind
	gesture_time = 0.48


## A struck recoil: a red flash and a short shove away from the blow.
func hurt(from_direction := 1.0) -> void:
	if dead:
		return
	var tween := create_tween()
	tween.tween_property(self, "modulate", Color(1.0, 0.45, 0.4), 0.06)
	tween.parallel().tween_property(self, "position:x", position.x + 6.0 * from_direction, 0.06)
	tween.tween_property(self, "modulate", Color.WHITE, 0.35)
	tween.parallel().tween_property(self, "position:x", position.x, 0.25)


## Collapse sideways around the feet and stay down.
func die(fall_direction := 1.0) -> void:
	if dead:
		return
	dead = true
	_hold_still()
	var tween := create_tween()
	tween.tween_property(self, "modulate", Color(1.0, 0.5, 0.45), 0.08)
	tween.tween_property(self, "rotation", fall_direction * 0.35, 0.18).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "rotation", fall_direction * PI * 0.47, 0.42) \
		.set_trans(Tween.TRANS_BOUNCE).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(self, "modulate", Color(0.62, 0.6, 0.58), 0.6)


## Knocked down in a fight: alive, but on the ground and out of it (D-41). Instant when restoring a state.
func knock_down(fall_direction := 1.0, instant := false) -> void:
	if dead:
		return
	dead = true
	_hold_still()
	if instant:
		rotation = fall_direction * PI * 0.47
		modulate = Color(0.85, 0.8, 0.78)
		return
	var tween := create_tween()
	tween.tween_property(self, "modulate", Color(1.0, 0.5, 0.45), 0.08)
	tween.tween_property(self, "rotation", fall_direction * PI * 0.47, 0.4) \
		.set_trans(Tween.TRANS_BOUNCE).set_ease(Tween.EASE_OUT)
	tween.parallel().tween_property(self, "modulate", Color(0.85, 0.8, 0.78), 0.5)


## Restore a body that died earlier in the journey without replaying the fall.
func lie_dead(fall_direction := 1.0) -> void:
	dead = true
	_hold_still()
	rotation = fall_direction * PI * 0.47
	modulate = Color(0.62, 0.6, 0.58)


## Undo a death pose (after rewinding the journey).
func revive() -> void:
	dead = false
	rotation = 0.0
	modulate = Color.WHITE


func _hold_still() -> void:
	if joints.is_empty():
		return
	for part_name in joints[facing]:
		var pivot: Node2D = joints[facing][part_name]
		pivot.rotation = 0.0
		pivot.position = rest_positions[facing][part_name]


