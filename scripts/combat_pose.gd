extends RefCounted
## Attack and guard poses for the cutout rig (GDD D-49): procedural, so one set covers every weapon anyone makes.
## Each attack is an anticipation pose held over the weapon's real wind-up (so it can be read and dodged),
## a quick strike, and a recovery. Angles are radians on the striking arm's pivot (positive swings forward on the
## right-facing view); "reach" pushes the held thing along its own axis (a thrust); "both" moves both arms.

const STRIKE_S := 0.15
const RECOVER_S := 0.25

# name: {wind: arm angle at the end of the wind-up, strike: at the blow, reach: px pushed along the weapon,
#        both: both arms together, torso: lean at the blow, hold: resting angle of the held thing}
const ATTACKS := {
	"punch": {"wind": -0.5, "strike": 1.2, "reach": 6.0, "both": false, "torso": 0.05},
	"stab": {"wind": -0.4, "strike": 1.1, "reach": 5.0, "both": false, "torso": 0.06},
	"thrust": {"wind": -0.3, "strike": 1.25, "reach": 9.0, "both": false, "torso": 0.08},
	"two_hand_thrust": {"wind": -0.2, "strike": 1.3, "reach": 13.0, "both": true, "torso": 0.1},
	"slash": {"wind": -2.2, "strike": 1.0, "reach": 0.0, "both": false, "torso": 0.1},
	"overhead": {"wind": -2.6, "strike": 0.9, "reach": 0.0, "both": false, "torso": 0.12},
	"two_hand_swing": {"wind": -2.0, "strike": 1.4, "reach": 0.0, "both": true, "torso": 0.14},
	"two_hand_overhead": {"wind": -2.9, "strike": 1.0, "reach": 0.0, "both": true, "torso": 0.16},
	"spin": {"wind": -3.1, "strike": 1.2, "reach": 0.0, "both": false, "torso": 0.08, "spins": 2.0},
	"spin_release": {"wind": -3.1, "strike": 1.3, "reach": 0.0, "both": false, "torso": 0.06, "spins": 2.0},
	"lash": {"wind": -2.4, "strike": 1.5, "reach": 0.0, "both": false, "torso": 0.06},
	"throw": {"wind": -2.5, "strike": 1.4, "reach": 0.0, "both": false, "torso": 0.12, "release": true},
	"draw_shoot": {"wind": 1.45, "strike": 1.45, "reach": -10.0, "both": true, "torso": 0.0, "draw": true},
	"pour": {"wind": 0.4, "strike": 1.6, "reach": 4.0, "both": true, "torso": 0.1, "tip": true},
	"bash": {"wind": -0.3, "strike": 1.0, "reach": 8.0, "both": false, "torso": 0.1},
}

# Resting angle of the held thing on the arm (radians from the painted diagonal), by how it is carried.
const HOLDS := {
	"punch": 0.0, "stab": 0.6, "slash": 0.35, "overhead": 0.35, "thrust": -0.2, "two_hand_thrust": -0.35,
	"two_hand_swing": 0.2, "two_hand_overhead": 0.3, "spin": 0.9, "spin_release": 0.9, "lash": 0.9, "throw": 0.4,
	"draw_shoot": -0.8, "pour": 0.8, "bash": 0.0,
}


## Where the striking arm is at time t (seconds) into an attack whose wind-up lasts windup_s.
static func arm_angle(animation: String, t: float, windup_s: float) -> float:
	var spec: Dictionary = ATTACKS.get(animation, ATTACKS["punch"])
	var wind: float = spec["wind"]
	var strike: float = spec["strike"]
	if t < windup_s:
		var k := _ease(t / maxf(windup_s, 0.001))
		var angle := wind * k
		if spec.has("spins"):  # Whirl it round over the wind-up.
			angle += sin(k * TAU * float(spec["spins"])) * 0.6
		return angle
	if t < windup_s + STRIKE_S:
		return lerpf(wind, strike, (t - windup_s) / STRIKE_S)
	var back := clampf((t - windup_s - STRIKE_S) / RECOVER_S, 0.0, 1.0)
	return lerpf(strike, 0.0, _ease(back))


## How far the held thing is pushed out along its axis (a thrust) at time t.
static func reach(animation: String, t: float, windup_s: float) -> float:
	var spec: Dictionary = ATTACKS.get(animation, ATTACKS["punch"])
	var push: float = spec["reach"]
	if spec.get("draw", false):  # A bow: the string hand draws back over the wind-up, then snaps forward.
		return push * _ease(clampf(t / maxf(windup_s, 0.001), 0.0, 1.0)) if t < windup_s else 0.0
	if t < windup_s:
		return -push * 0.3 * _ease(t / maxf(windup_s, 0.001))
	if t < windup_s + STRIKE_S:
		return lerpf(-push * 0.3, push, (t - windup_s) / STRIKE_S)
	return lerpf(push, 0.0, clampf((t - windup_s - STRIKE_S) / RECOVER_S, 0.0, 1.0))


static func torso_lean(animation: String, t: float, windup_s: float) -> float:
	var spec: Dictionary = ATTACKS.get(animation, ATTACKS["punch"])
	var lean: float = spec["torso"]
	if t < windup_s:
		return -lean * 0.5 * _ease(t / maxf(windup_s, 0.001))
	if t < windup_s + STRIKE_S:
		return lerpf(-lean * 0.5, lean, (t - windup_s) / STRIKE_S)
	return lerpf(lean, 0.0, clampf((t - windup_s - STRIKE_S) / RECOVER_S, 0.0, 1.0))


static func both_arms(animation: String) -> bool:
	return bool(ATTACKS.get(animation, ATTACKS["punch"]).get("both", false))


static func duration(windup_s: float) -> float:
	return windup_s + STRIKE_S + RECOVER_S


static func hold_angle(animation: String) -> float:
	return float(HOLDS.get(animation, 0.3))


static func _ease(x: float) -> float:
	x = clampf(x, 0.0, 1.0)
	return x * x * (3.0 - 2.0 * x)
