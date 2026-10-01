extends Node
## Talking to the service (backend/app.py): where it is, one JSON request, one painted picture.

var game: Node2D # The game (scripts/main.gd), whose child this is.


const DEFAULT_SERVER := "http://127.0.0.1:8765"


var server := DEFAULT_SERVER # --server=URL or GAME_SERVER (tools/check.ps1 runs a throwaway backend).


static func address() -> String:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--server="):
			return arg.trim_prefix("--server=")
	return OS.get_environment("GAME_SERVER") if OS.has_environment("GAME_SERVER") else DEFAULT_SERVER


func api(method: HTTPClient.Method, path: String, body: Dictionary = {}, timeout := 5.0) -> Dictionary:
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
	var data = JSON.parse_string(text) if text.strip_edges().left(1) in ["{", "["] else null
	game._prof("parse " + path.get_slice("?", 0).get_file(), parse_started, (completed[3] as PackedByteArray).size())
	return {"ok": status >= 200 and status < 300 and typeof(data) == TYPE_DICTIONARY,
		"status": status, "data": data}


## A POST that may have been lost: tried once more when there was no answer or the service stumbled (the same
## request id makes that safe). A 503 (no model to ask) is final unless retry_unavailable.
func post(path: String, body: Dictionary = {}, timeout := 5.0, retry_unavailable := true) -> Dictionary:
	var reply := await api(HTTPClient.METHOD_POST, path, body, timeout)
	var status := int(reply.status)
	if not reply.ok and (status == 0 or status >= 500) and (retry_unavailable or status != 503):
		reply = await api(HTTPClient.METHOD_POST, path, body, timeout)
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
