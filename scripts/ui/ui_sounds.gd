extends Node
## Soft UI sounds made in code: a wooden click, a paper rustle to open, a lighter one to close.
## They play on the master bus, so the volume setting applies.

var players: Dictionary = {}


func _ready() -> void:
	for kind in ["click", "open", "close", "error"]:
		var player := AudioStreamPlayer.new()
		player.stream = _make(kind)
		player.volume_db = {"click": -20.0, "open": -24.0, "close": -27.0, "error": -22.0}[kind]
		add_child(player)
		players[kind] = player


func play(kind: String) -> void:
	var player: AudioStreamPlayer = players.get(kind)
	if player:
		player.pitch_scale = randf_range(0.94, 1.06)
		player.play()


func _make(kind: String) -> AudioStreamWAV:
	var rate := 22050
	var length: int = {"click": 900, "open": 5200, "close": 3400, "error": 4400}[kind]
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
		var sample := int(clampf(value * envelope, -1.0, 1.0) * 20000)
		data.append(sample & 255)
		data.append((sample >> 8) & 255)
	var stream := AudioStreamWAV.new()
	stream.format = AudioStreamWAV.FORMAT_16_BITS
	stream.mix_rate = rate
	stream.data = data
	return stream
