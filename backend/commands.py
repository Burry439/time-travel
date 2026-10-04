"""One way to run a player's command on a journey (GDD D-58). Every route that changes the world goes through
here: load the journey, the checks every command needs, a snapshot to measure the change from, and saving it.

    @router.post("/runs/{run_id}/strike")
    @commands.answers
    def strike(run_id: str, request: Strike):
        with commands.open(run_id, request) as cmd:
            ...change cmd.state...
            cmd.save("fight")
        return {"state": cmd.state, "duplicate": False}

A command that asks a model does it between two ``open``s, never holding the lock: the first checks and gathers
what the model needs (and claims the journey, ``cmd.claim()``); the second, ``reopen``, runs on the latest world.
"""

from __future__ import annotations

import functools
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException

import attempts
import patch
import store
from shapes import State


class Reply(Exception):
    """Stop here and answer with this body: a repeated request gets what it got the first time."""

    def __init__(self, body: dict):
        super().__init__("reply")
        self.body = body


def answers(route: Callable) -> Callable:
    """Wraps a route so that a Reply raised anywhere in it becomes its answer."""

    @functools.wraps(route)
    def wrapper(*args, **kwargs):
        try:
            return route(*args, **kwargs)
        except Reply as reply:
            return reply.body

    return wrapper


class Command:
    """The journey being changed, where the change is measured from, and saving it."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        run: sqlite3.Row,
        state: State,
        request_id: str | None,
        body: str | None = None,
    ):
        self.connection, self.run, self.state = connection, run, state
        self.request_id = request_id
        self.body = body
        self.before = patch.snapshot(state)
        self.saves = 0

    @property
    def run_id(self) -> str:
        return self.state["run_id"]

    @property
    def developer(self) -> bool:
        return self.run["mode"] == "developer"

    def save(self, kind: str, tick: int | None = None, meta: dict | None = None, request_id: str | None = None) -> None:
        """Save what changed since the last save (or since loading) as one event. A command's further saves get
        request ids ``id+1``, ``id+2``, so a repeat of it is answered with the state after all of them."""
        if request_id is None and self.request_id is None:  # A command no request asked for (the story moving on).
            request_id = f"{kind}:{uuid4().hex}"
        elif request_id is None:
            request_id = self.request_id if self.saves == 0 else f"{self.request_id}+{self.saves}"
            self.saves += 1
        tick = self.state["sim_time_ms"] // 1000 if tick is None else tick
        self.before = store.record(self.connection, self.before, self.state, kind, request_id, tick, meta)
        if self.body is not None and self.request_id is not None:
            self.connection.execute(
                "INSERT INTO action_requests (run_id,request_id,final_seq,request_json) VALUES (?,?,?,?) ON CONFLICT(run_id,request_id) DO UPDATE SET final_seq=excluded.final_seq",
                (self.run_id, self.request_id, self.state["event_seq"], self.body),
            )

    def claim(self) -> None:
        """One Try Something, conversation or round at a time on a journey; release() when it's done."""
        if self.run_id in attempts.busy_runs:
            raise HTTPException(409, {"reason": "in_progress"})
        attempts.busy_runs.add(self.run_id)


def release(run_id: str) -> None:
    attempts.busy_runs.discard(run_id)


def _playable(state: State) -> None:
    if state["inside_city"] or not state["player"]["alive"]:
        raise HTTPException(409, "This journey is over.")


@contextmanager
def open(
    run_id: str,
    request=None,
    *,
    playable: bool = True,
    stale: bool = True,
    developer: bool = False,
    body: dict | None = None,
    duplicate: Callable[[sqlite3.Row, dict, sqlite3.Connection], dict] | None = None,
) -> Iterator[Command]:
    """Load the journey under the lock and check what every command must: a repeat of an earlier request (answered
    with what it got then), a stale view (409), a journey that's over, a developer-only control.

    body: the request's content, for commands that must never run twice with different content under one request id
    (attempts and rounds); duplicate builds their repeat's answer from (run, saved state, connection)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        if developer and run["mode"] != "developer":
            raise HTTPException(403, "Developer control is unavailable in normal mode")
        request_id = getattr(request, "request_id", None)
        body_json = json.dumps(body, sort_keys=True) if body is not None else None
        if request is not None:
            if body_json is not None:
                _check_body(connection, run, run_id, request_id, body_json, duplicate)
            version = request.expected_version if stale else state["event_seq"]
            prior = store.check_request(connection, state, version, request_id)
            if prior is not None:
                raise Reply({"state": store.state_at(connection, run, prior), "duplicate": True})
        if playable:
            _playable(state)
        yield Command(connection, run, state, request_id, body_json)


def _check_body(connection, run, run_id: str, request_id: str, body_json: str, duplicate) -> None:
    prior = connection.execute(
        "SELECT final_seq,request_json FROM action_requests WHERE run_id=? AND request_id=?", (run_id, request_id)
    ).fetchone()
    if prior:
        if prior["request_json"] != body_json:
            raise HTTPException(409, {"reason": "request_id_conflict"})
        saved = store.state_at(connection, run, prior["final_seq"])
        raise Reply(duplicate(run, saved, connection) if duplicate else {"state": saved, "duplicate": True})
    if connection.execute("SELECT 1 FROM events WHERE run_id=? AND request_id=?", (run_id, request_id)).fetchone():
        raise HTTPException(409, {"reason": "request_id_conflict"})


@contextmanager
def reopen(run_id: str, request, body: dict | None = None, stale: bool = True) -> Iterator[Command]:
    """The same command again after a model has answered: the latest world (still not stale for this request,
    unless stale=False: what it adds doesn't depend on what the player saw)."""
    with store.lock, store.db() as connection:
        run, state = store.load_run(connection, run_id)
        _playable(state)
        if stale and store.is_stale(state, request.expected_version):
            raise HTTPException(409, {"reason": "stale_state", "state": state})
        body_json = json.dumps(body, sort_keys=True) if body is not None else None
        yield Command(connection, run, state, request.request_id, body_json)


@contextmanager
def peek(run_id: str) -> Iterator[dict]:
    """The journey as it is, read-only (no lock): for deciding which command a request is."""
    with store.db() as connection:
        _, state = store.load_run(connection, run_id)
    yield state
