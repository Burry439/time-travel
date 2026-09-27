shader_type canvas_item;
void vertex() {
	float rooted = clamp(-VERTEX.y / 650.0, 0.0, 1.0);
	float phase = MODEL_MATRIX[3].x * 0.013;
	VERTEX.x += (sin(TIME * 1.2 + phase) + sin(TIME * 0.71 + phase) * 0.4) * 3.0 * rooted;
}
