extends Node
## Talking to the service (backend/app.py): where it is, one JSON request, one painted picture.

var game: Node2D # The game (scripts/main.gd), whose child this is.


const DEFAULT_SERVER := "http://127.0.0.1:8765"


var server := DEFAULT_SERVER # --server=URL or GAME_SERVER (tools/check.ps1 runs a throwaway backend).

## What the player is waiting on right now, in words (D-70): {ticket: {"label", "since"}}. The busy indicator shows
## the newest one. Background traffic (walking, the clock, pictures, the village's own life) is never listed.
var waiting := {}
var _ticket := 0
const QUIET := "-" # A request the player isn't waiting on.


## What a request is, to someone waiting on it; QUIET for background traffic.
static func busy_label(method: HTTPClient.Method, path: String) -> String:
	var route := path.get_slice("?", 0)
	if route == "/runs":
		return "Starting a new journey…" if method == HTTPClient.METHOD_POST else QUIET
	if route.begins_with("/runs/") and route.count("/") == 2:
		return "Loading your journey…" if method == HTTPClient.METHOD_GET else QUIET
	for ending in [["/act", "Working out what happens…"], ["/craft", "Working out what happens…"],
			["/encounter/act", "They're thinking…"], ["/say", "They're thinking…"], ["/quick", "Working…"],
			["/rewind", "Rewinding your journey…"], ["/device/ask", "The device is thinking…"],
			["/checkpoint", "Saving your journey…"], ["/result", "Loading your results…"],
			["/equip", "Changing your gear…"], ["/treat", "Tending the wound…"]]:
		if route.ends_with(ending[0]):
			return ending[1]
	if route == "/training":
		return "Loading the training levels…"
	return QUIET


static func address() -> String:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--server="):
			return arg.trim_prefix("--server=")
	return OS.get_environment("GAME_SERVER") if OS.has_environment("GAME_SERVER") else DEFAULT_SERVER


func api(method: HTTPClient.Method, path: String, body: Dictionary = {}, timeout := 5.0, busy := "") -> Dictionary:
	var label := busy if not busy.is_empty() else busy_label(method, path)
	var ticket := 0
	if label != QUIET: # Someone is waiting on this: the busy indicator says what for (D-70).
		_ticket += 1
		ticket = _ticket
		waiting[ticket] = {"label": label, "since": Time.get_ticks_msec()}
	var reply := await _api(method, path, body, timeout)
	waiting.erase(ticket)
	return reply


func _api(method: HTTPClient.Method, path: String, body: Dictionary, timeout: float) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)
	request.timeout = timeout
	var payload := JSON.stringify(body) if method != HTTPClient.METHOD_GET else ""
	var err := request.request(server + path, ["Content-Type: application/json"], method, payload)
	if err != OK:
		request.queue_free()
		return {"ok": false, "status": 0}
	var completed: Array = await request.request_completed
	request.queue_free()
	var status := int(completed[1])
	var parse_started := Time.get_ticks_usec()
	var text := (completed[3] as PackedByteArray).get_string_from_utf8()
	# Only JSON is parsed: an error page ("Internal Server Error") is a failed reply, not something to parse.
	var parsed := {"data": null}
	if text.strip_edges().left(1) in ["{", "["]:
		# Full world replies can be large. Decode off the render thread, then accept on it in event order.
		var job := WorkerThreadPool.add_task(_parse_payload.bind(text, parsed), false, "world JSON")
		while not WorkerThreadPool.is_task_completed(job):
			await get_tree().process_frame
		WorkerThreadPool.wait_for_task_completion(job)
	var data = parsed.data
	game._prof("parse " + path.get_slice("?", 0).get_file(), parse_started, (completed[3] as PackedByteArray).size())
	return {"ok": status >= 200 and status < 300 and typeof(data) == TYPE_DICTIONARY,
		"status": status, "data": data}


static func _parse_payload(payload: String, parsed: Dictionary) -> void:
	parsed.data = JSON.parse_string(payload)


## A POST that may have been lost: tried once more when there was no answer or the service stumbled (the same
## request id makes that safe). A 503 (no model to ask) is final unless retry_unavailable.
func post(path: String, body: Dictionary = {}, timeout := 5.0, retry_unavailable := true, busy := "") -> Dictionary:
	var started := Time.get_ticks_msec()
	var reply := await api(HTTPClient.METHOD_POST, path, body, timeout, busy)
	var status := int(reply.status)
	if not reply.ok and (status == 0 or status >= 500) and (retry_unavailable or status != 503):
		var remaining := timeout - float(Time.get_ticks_msec() - started) / 1000.0
		if remaining > 0.1:
			reply = await api(HTTPClient.METHOD_POST, path, body, remaining, busy)
	return reply


func fetch_asset(asset_id: String) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)
	request.timeout = 15.0
	if request.request(server + "/assets/" + asset_id) != OK:
		request.queue_free()
		return {"status": 0, "body": PackedByteArray()}
	var completed: Array = await request.request_completed
	request.queue_free()
	return {"status": int(completed[1]), "body": completed[3]}
