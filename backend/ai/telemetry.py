"""Per-call model telemetry, stored beside the run in SQLite (table created by app.db)."""

from __future__ import annotations

import sqlite3


def record(
    connection: sqlite3.Connection,
    run_id: str,
    role: str,
    model: str | None,
    prompt_version: str,
    latency_ms: int,
    ok: bool,
    error: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    attempts: int = 1,
) -> None:
    connection.execute(
        "INSERT INTO model_calls (run_id,role,model,prompt_version,latency_ms,input_tokens,output_tokens,"
        "attempts,ok,error) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, role, model, prompt_version, latency_ms, input_tokens, output_tokens, attempts, int(ok), error),
    )


def calls_for_run(connection: sqlite3.Connection, run_id: str, decider: bool = False) -> int:
    """Model calls so far: the writing roles (judge, voice, memory, pictures) or, separately, the decider (D-37:
    people deciding their day would otherwise use up the allowance meant for writing)."""
    where = "role='decider'" if decider else "role!='decider'"
    return int(
        connection.execute(
            f"SELECT COALESCE(SUM(attempts),0) FROM model_calls WHERE run_id=? AND {where}", (run_id,)
        ).fetchone()[0]
    )


def recent(connection: sqlite3.Connection, run_id: str, limit: int = 50) -> list[dict]:
    rows = connection.execute(
        "SELECT * FROM model_calls WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)
    ).fetchall()
    return [dict(row) for row in rows]
