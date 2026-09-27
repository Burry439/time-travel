extends Node2D
var dust: Array[Dictionary] = []
var marker := Vector2.ZERO
var has_target := false
var clock := 0.0
var sound: AudioStreamPlayer
var pickup_sound: AudioStreamPlayer

func _ready() -> void:
	sound = AudioStreamPlayer.new()
	sound.volume_db = -25
	sound.stream = _synthesize(false)
	add_child(sound)
	pickup_sound = AudioStreamPlayer.new()
	pickup_sound.volume_db = -22
	pickup_sound.stream = _synthesize(true)
	add_child(pickup_sound)

func _synthesize(chime: bool) -> AudioStreamWAV:
	var data := PackedByteArray()
	var rate := 22050
	var samples := 4400 if chime else 1700
	var rng := RandomNumberGenerator.new()
	rng.seed = 128
	var low := 0.0
	for i in samples:
		var t := float(i) / rate
		var envelope := pow(1.0 - float(i) / samples, 2.5) * minf(1.0, i / 90.0)
		low = lerpf(low, rng.randf_range(-1, 1), 0.25)
		var wave := (sin(TAU * 660 * t) * 0.5 + sin(TAU * 990 * t) * 0.18) if chime else low
		var value := int(wave * envelope * 24000)
		data.append(value & 255)
		data.append((value >> 8) & 255)
	var stream := AudioStreamWAV.new()
	stream.format = AudioStreamWAV.FORMAT_16_BITS
	stream.mix_rate = rate
	stream.data = data
	return stream

func step(at: Vector2, running: bool) -> void:
	sound.pitch_scale = randf_range(0.88, 1.12)
	sound.play()
	for i in (3 if running else 1):
		dust.append({"p": at + Vector2(randf_range(-8, 8), 2), "age": 0.0, "v": Vector2(randf_range(-8, 8), -9)})

func _process(delta: float) -> void:
	clock += delta
	for mote in dust:
		mote.age += delta
		mote.p += mote.v * delta
	dust = dust.filter(func(mote: Dictionary) -> bool: return mote.age < 0.5)
	queue_redraw()

func _draw() -> void:
	for mote in dust:
		draw_circle(mote.p, 2.0 + mote.age * 6, Color(0.84, 0.76, 0.55, (1.0 - mote.age * 2) * 0.25))
	if has_target:
		draw_set_transform(marker, 0, Vector2(1, 0.45))
		draw_arc(Vector2.ZERO, 28 + sin(clock * 3) * 1.5, 0, TAU, 40, Color(0.98, 0.86, 0.55, 0.9), 2, true)
