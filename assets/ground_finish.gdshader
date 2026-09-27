shader_type canvas_item;
uniform sampler2D ground_source : repeat_enable, filter_linear;
void fragment() {
	// Finer terrain grain keeps tiny grass details in proportion to the actors.
	vec3 base = texture(ground_source, UV * 2.3).rgb;
	float gray = dot(base, vec3(0.299, 0.587, 0.114));
	base = mix(vec3(gray), base, 0.68);
	vec2 world_pos = UV * vec2(3072.0, 2304.0);
	float courtyard = 1.0 - smoothstep(0.25, 1.0, length((world_pos - vec2(1110.0, 1640.0)) / vec2(490.0, 310.0)));
	base = mix(base, vec3(0.57, 0.50, 0.38), courtyard * 0.24);
	COLOR = vec4(base * vec3(0.84, 0.91, 0.73), 1.0);
}
