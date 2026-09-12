"""Direct access to the local Walnut Event Inbox.

This keeps wake runs on the main Termux MCP: no public endpoint or shell/SQLite
commands are needed just to inspect and acknowledge local events.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.path.expanduser("~/.local/state/termux-mcp/walnut-inbox"))
DB = STATE_DIR / "events.sqlite3"
HEARTBEAT = STATE_DIR / "heartbeat.json"
_VALID_STATUS = {"pending", "acknowledged", "archived", "all"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    if not DB.exists():
        raise RuntimeError("Walnut Inbox database does not exist yet")
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["payload"] = json.loads(item["payload"])
    except Exception:
        pass
    return item


def list_events(status: str = "pending", limit: int = 20, source: str | None = None) -> dict[str, Any]:
    status = status.strip().lower()
    if status not in _VALID_STATUS:
        raise ValueError("status must be pending, acknowledged, archived, or all")
    limit = max(1, min(int(limit), 100))
    clauses: list[str] = []
    params: list[Any] = []
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source.strip())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    # Priority first makes a bounded wake useful even with a noisy queue.
    sql = (
        "SELECT * FROM events" + where +
        " ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'normal' THEN 2 ELSE 3 END, created_at ASC LIMIT ?"
    )
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        pending = conn.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]
    return {"pending_count": pending, "events": [_row(r) for r in rows]}


def get_event(event_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id.strip(),)).fetchone()
    if not row:
        raise ValueError("event not found")
    return _row(row)


def ack_event(event_id: str, note: str = "") -> dict[str, Any]:
    event_id = event_id.strip()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise ValueError("event not found")
        if row["status"] != "archived":
            conn.execute(
                "UPDATE events SET status='acknowledged', acknowledged_at=?, note=? WHERE id=?",
                (_now(), note.strip()[:1000], event_id),
            )
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return _row(row)


def status() -> dict[str, Any]:
    with _connect() as conn:
        counts = {r["status"]: r["count"] for r in conn.execute(
            "SELECT status, COUNT(*) AS count FROM events GROUP BY status"
        ).fetchall()}
        last = conn.execute("SELECT created_at, source, type FROM events ORDER BY created_at DESC LIMIT 1").fetchone()
    heartbeat = None
    try:
        heartbeat = json.loads(HEARTBEAT.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "ok": True,
        "pending": counts.get("pending", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "archived": counts.get("archived", 0),
        "latest_event": dict(last) if last else None,
        "heartbeat": heartbeat,
    }
