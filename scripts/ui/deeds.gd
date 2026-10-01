extends RefCounted
## Deeds (GDD D-55) and standing, as they look: the service works out which deeds a journey has and the word for
## where each person stands (backend/views.py, sent with every state as its view); here are their order, colours
## and what someone used to be, for the journal and the toasts.

const STANDING_ORDER := ["hostile", "unknown", "wary", "neutral", "friendly", "would_speak"] # Coldest first.
const STANDING_BEFORE := {"unknown": "You've only just met.", "hostile": "Was hostile to you.", "wary": "Was wary of you.",
	"neutral": "Was neither for nor against you.", "friendly": "Was friendly.", "would_speak": "Would have spoken for you."}
const STANDING_COLOURS := {"unknown": Color("8a7a66"), "hostile": Color("8f2a1c"), "wary": Color("a0621b"),
	"neutral": Color("6a5238"), "friendly": Color("3d6b2a"), "would_speak": Color("1f6b4f")}


## The journey's deeds, as the service worked them out from the world (backend/views.py): [{id, title, text, who}].
static func compute(state: Dictionary) -> Array:
	return _view(state).get("deeds", [])


## Where someone stands, in the service's words (the same words everywhere: journal, toasts, the device).
static func word(state: Dictionary, standing: String) -> String:
	return str(_view(state).get("standing_words", {}).get(standing, standing))


static func _view(state: Dictionary) -> Dictionary:
	return state.get("view", {}) if typeof(state.get("view")) == TYPE_DICTIONARY else {}


static func standing_word(npc: Dictionary) -> String:
	var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
	return str(their_mind.get("standing", "unknown")) if their_mind.get("standing") != null else "unknown"
