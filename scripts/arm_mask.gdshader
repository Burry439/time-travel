shader_type canvas_item;
uniform vec2 atlas_size;
uniform vec2 right_a; uniform vec2 right_b; uniform vec2 right_c;
uniform vec2 left_a; uniform vec2 left_b; uniform vec2 left_c;
uniform float width;
uniform bool fill_body = false;
uniform float body_x;
float segment_distance(vec2 p, vec2 a, vec2 b) {
	vec2 ab = b-a;
	return length(p-a-ab*clamp(dot(p-a,ab)/max(dot(ab,ab),0.01),0.0,1.0));
}
void fragment() {
	vec2 p = UV * atlas_size;
	bool arm = min(segment_distance(p,right_a,right_b),segment_distance(p,left_a,left_b)) < width
		|| min(segment_distance(p,right_b,right_c),segment_distance(p,left_b,left_c)) < width*.78;
	vec4 paint = texture(TEXTURE, UV);
	if (arm) {
		paint = fill_body ? texture(TEXTURE, vec2(body_x/atlas_size.x, UV.y)) : vec4(0.0);
	}
	COLOR *= paint;
}
