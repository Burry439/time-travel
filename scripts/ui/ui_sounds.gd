extends Node
## Soft UI sounds made in code: a wooden click, a paper rustle to open, a lighter one to close, and (D-55) a chime
## when something works, a soft thud when it doesn't, a little fanfare for a deed, and a bell for news.
## They play on the master bus, so the volume setting applies.

var players: Dictionary = {}


func _ready() -> void:
	for kind in ["click", "open", "close", "error", "success", "fail", "deed", "toast"]:
		var player := AudioStreamPlayer.new()
		player.stream = _make(kind)
		player.volume_db = {"click": -20.0, "open": -24.0, "close": -27.0, "error": -22.0, "success": -18.0,
			"fail": -20.0, "deed": -16.0, "toast": -22.0}[kind]
		add_child(player)
		players[kind] = player


func play(kind: String) -> void:
	var player: AudioStreamPlayer = players.get(kind)
	if player:
		player.pitch_scale = randf_range(0.94, 1.06)
		player.play()


func _make(kind: String) -> AudioStreamWAV:
	var rate := 22050
	var length: int = {"click": 900, "open": 5200, "close": 3400, "error": 4400, "success": 9000, "fail": 5000,
		"deed": 16000, "toast": 7000}[kind]
	var rng := RandomNumberGenerator.new()
	rng.seed = kind.hash()
	var data := PackedByteArray()
	var smooth := 0.0
	for i in length:
		var t := float(i) / rate
		var envelope := pow(1.0 - float(i) / length, 3.0 if kind == "click" else 1.6) * minf(1.0, i / 40.0)
		var value := 0.0
		match kind:
			"click": # A knock on wood: a low thud with a short tap on top.
				value = sin(TAU * 190.0 * t) * 0.7 + sin(TAU * 1250.0 * t) * 0.3 * exp(-t * 90.0)
			"open", "close": # Paper: filtered noise with a gentle swell.
				smooth = lerpf(smooth, rng.randf_range(-1, 1), 0.18 if kind == "open" else 0.3)
				value = smooth * 1.6 * sin(PI * float(i) / length)
			"error":
				value = (sin(TAU * 220.0 * t) + sin(TAU * 233.0 * t)) * 0.35
			"success": # Two rising notes, like a small bell: it worked.
				var note := 523.25 if t < 0.16 else 783.99
				value = sin(TAU * note * t) * 0.5 + sin(TAU * note * 2.0 * t) * 0.15
			"fail": # A soft, low wooden thud falling away: it didn't.
				value = sin(TAU * lerpf(180.0, 110.0, float(i) / length) * t) * 0.8
			"deed": # A little three-note fanfare.
				var step := 392.0 if t < 0.14 else (523.25 if t < 0.28 else 659.25)
				value = sin(TAU * step * t) * 0.45 + sin(TAU * step * 1.5 * t) * 0.12
			"toast": # One soft bell.
				value = sin(TAU * 880.0 * t) * 0.35 * exp(-t * 6.0) + sin(TAU * 1320.0 * t) * 0.1 * exp(-t * 9.0)
		var sample := int(clampf(value * envelope, -1.0, 1.0) * 20000)
		data.append(sample & 255)
		data.append((sample >> 8) & 255)
	var stream := AudioStreamWAV.new()
	stream.format = AudioStreamWAV.FORMAT_16_BITS
	stream.mix_rate = rate
	stream.data = data
	return stream
