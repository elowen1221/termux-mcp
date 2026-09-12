"""Walnut Journal: a small append-only record of real wake activity."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.path.expanduser("~/.local/state/termux-mcp/walnut-journal"))
DB = STATE_DIR / "journal.sqlite3"
KINDS = {"activity", "reflection", "observation"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            related_task_ids TEXT NOT NULL DEFAULT '[]',
            source_refs TEXT NOT NULL DEFAULT '[]',
            note TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    try:
        os.chmod(DB, 0o600)
    except OSError:
        pass
    return conn


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["related_task_ids"] = json.loads(item["related_task_ids"])
    item["source_refs"] = json.loads(item["source_refs"])
    return item


def append_entry(summary: str, kind: str = "activity", related_task_ids: list[str] | None = None,
                 source_refs: list[str] | None = None, note: str = "") -> dict[str, Any]:
    summary = summary.strip()
    kind = kind.strip().lower()
    if not summary:
        raise ValueError("summary is required")
    if len(summary) > 2000:
        raise ValueError("summary is too long (max 2000)")
    if kind not in KINDS:
        raise ValueError("kind must be activity, reflection, or observation")
    entry_id = "journal_" + uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?)",
            (entry_id, _now(), kind, summary, json.dumps(related_task_ids or []),
             json.dumps(source_refs or []), note.strip()[:4000]),
        )
        row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    return _decode(row)


def recent_entries(limit: int = 10, kind: str = "all") -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    kind = kind.strip().lower()
    if kind not in KINDS | {"all"}:
        raise ValueError("invalid kind")
    with _connect() as conn:
        if kind == "all":
            rows = conn.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM entries WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)).fetchall()
    return {"entries": [_decode(row) for row in rows]}
