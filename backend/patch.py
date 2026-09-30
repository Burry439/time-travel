"""What changed between two states of a journey, and how to apply it (GDD D-58). Every event stores only this.

A patch mirrors the state's shape, holding only what changed. At each key, the change is one of:

- ``{"=": value}``: the value is now this;
- ``{"-": 1}``: the key is gone;
- ``{"+": [items]}``: a list grew at the end (the journal, memories, talk);
- ``{"<": n}``: a list lost its first n items (a walking path as it's walked);
- ``{"@": {id: change}}``: a list of records (the people) changed record by record, each record's change in the
  same form;
- any other dict: changes inside a dict, key by key.

Lists of records that keep the same ids in the same order are diffed record by record; a list that only grew at
the end or only lost items from the front says so; anything else is replaced whole.
"""

from __future__ import annotations

import json
from typing import Any

Patch = dict[str, Any]
SET, DELETE, APPEND, DROP, RECORDS = "=", "-", "+", "<", "@"


def snapshot(state: dict) -> dict:
    """A deep, JSON-clean copy: what the state is as saved (tuples become lists, as they would on a reload)."""
    return json.loads(json.dumps(state))


def diff(before: dict, after: dict) -> Patch:
    return _dict_changes(before, after)


def _record_ids(items: list) -> list | None:
    """The ids of a list of records (dicts that each have a distinct id), else None."""
    ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    return ids if None not in ids and len(set(ids)) == len(ids) else None


def _dict_changes(before: dict, after: dict) -> Patch:
    changes: Patch = {key: {DELETE: 1} for key in before if key not in after}
    for key, value in after.items():
        if key not in before:
            changes[key] = {SET: value}
        elif before[key] != value:
            changes[key] = _change(before[key], value)
    return changes


def _change(before: Any, after: Any) -> Patch:
    if isinstance(before, dict) and isinstance(after, dict):
        return _dict_changes(before, after)
    if isinstance(before, list) and isinstance(after, list):
        ids = _record_ids(before)
        if ids is not None and ids == _record_ids(after):
            return {RECORDS: {old["id"]: _dict_changes(old, new) for old, new in zip(before, after) if old != new}}
        if len(after) > len(before) and after[: len(before)] == before:
            return {APPEND: after[len(before) :]}
        if len(after) < len(before) and before[len(before) - len(after) :] == after:
            return {DROP: len(before) - len(after)}
    return {SET: after}


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def apply(state: dict, changes: Patch) -> None:
    """Change state in place. Values are copied, so a patch can be applied again (replay, retries)."""
    for key, change in changes.items():
        if SET in change:
            state[key] = _copy(change[SET])
        elif DELETE in change:
            del state[key]
        elif APPEND in change:
            state[key].extend(_copy(change[APPEND]))
        elif DROP in change:
            del state[key][: change[DROP]]
        elif RECORDS in change:
            records = {item["id"]: item for item in state[key]}
            for record_id, record_changes in change[RECORDS].items():
                apply(records[record_id], record_changes)
        else:
            apply(state[key], change)
