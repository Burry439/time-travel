extends RefCounted
## Deeds (GDD D-55): the milestones of a journey, read from what really happened in the world (never arbitrary
## achievements): your first invention, someone amazed, someone helped, a deal agreed and kept, a friend made,
## someone speaking for you, word of you spreading, the gate opening. One function, so the journal, the toasts
## and tests all agree. Each deed: {id, title, text, who (an npc id or "")}.

const STANDING_WORDS := {"unknown": "Doesn't know you", "hostile": "Hostile", "wary": "Wary", "neutral": "Neutral",
	"friendly": "Friendly", "would_speak": "Would speak for you"}
const STANDING_ORDER := ["hostile", "unknown", "wary", "neutral", "friendly", "would_speak"] # Coldest first.
const STANDING_BEFORE := {"unknown": "You've only just met.", "hostile": "Was hostile to you.", "wary": "Was wary of you.",
	"neutral": "Was neither for nor against you.", "friendly": "Was friendly.", "would_speak": "Would have spoken for you."}
const STANDING_COLOURS := {"unknown": Color("8a7a66"), "hostile": Color("8f2a1c"), "wary": Color("a0621b"),
	"neutral": Color("6a5238"), "friendly": Color("3d6b2a"), "would_speak": Color("1f6b4f")}


static func compute(state: Dictionary) -> Array:
	var deeds: Array = []
	var names := {}
	for npc in state.get("npcs", []):
		names[str(npc.id)] = str(npc.name)
	var made: Array = state.get("objects", {}).values().filter(func(o) -> bool: return o.get("created_by") == "player")
	if not made.is_empty():
		deeds.append({"id": "first_made", "title": "Your first invention",
			"text": "You made a %s. Nobody in this world had one until you did." % str(made[0].name), "who": ""})
	for npc in state.get("npcs", []):
		var id := str(npc.id)
		var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
		for memory in their_mind.get("memories", []):
			if memory.get("kind") == "demonstration" and str(memory.get("wonder", "")) in ["clever", "uncanny"] \
					and memory.get("clarity") == "clear":
				deeds.append({"id": "amazed:" + id, "title": "%s was amazed" % npc.name,
					"text": "%s saw your %s work, and has never seen anything like it." % [npc.name, str(memory.get("item", "invention"))],
					"who": id})
				break
		for memory in their_mind.get("memories", []):
			if memory.get("kind") in ["help", "gift"] and str(memory.get("victim", "")) == id and memory.get("clarity") != "vague":
				deeds.append({"id": "helped:" + id, "title": "You helped %s" % npc.name,
					"text": "%s won't forget it." % npc.name, "who": id})
				break
		var standing := str(their_mind.get("standing", ""))
		if standing in ["friendly", "would_speak"]:
			deeds.append({"id": "friend:" + id, "title": "A friend: %s" % npc.name,
				"text": "%s thinks well of you." % npc.name, "who": id})
		if standing == "would_speak":
			deeds.append({"id": "would_speak:" + id, "title": "%s would speak for you" % npc.name,
				"text": "Ask, and %s would put in a word for you." % npc.name, "who": id})
		for memory in their_mind.get("memories", []):
			if memory.get("kind") == "vouch":
				var by := str(memory.get("by", ""))
				deeds.append({"id": "vouched:" + by + ":" + id, "title": "%s spoke for you" % names.get(by, "Someone"),
					"text": "%s went to %s and spoke for you." % [names.get(by, "Someone"), npc.name], "who": by})
			if memory.get("kind") == "told":
				var teller := str(memory.get("by", ""))
				deeds.append({"id": "news:" + teller + ":" + id, "title": "Word is spreading",
					"text": "%s told %s about you." % [names.get(teller, "Someone"), npc.name], "who": teller})
	for deal in state.get("agreements", {}).values():
		var issuer := str(deal.get("issuer", ""))
		if str(deal.get("status", "")) in ["accepted", "fulfilled"]:
			deeds.append({"id": "deal:" + str(deal.id), "title": "A deal with %s" % names.get(issuer, "someone"),
				"text": "You agreed to %s." % str(deal.get("task", "help")), "who": issuer})
		if str(deal.get("status", "")) == "fulfilled":
			deeds.append({"id": "kept:" + str(deal.id), "title": "You kept your word",
				"text": "%s is satisfied: you did what you promised." % names.get(issuer, "They"), "who": issuer})
	if typeof(state.get("admitted")) == TYPE_DICTIONARY or state.get("inside_city", false):
		deeds.append({"id": "admitted", "title": "The gate opens", "text": "You're allowed into the city.", "who": ""})
	return deeds


static func standing_word(npc: Dictionary) -> String:
	var their_mind = npc.get("mind") if typeof(npc.get("mind")) == TYPE_DICTIONARY else {}
	return str(their_mind.get("standing", "unknown")) if their_mind.get("standing") != null else "unknown"
