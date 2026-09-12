"""Walnut Board: a lightweight persistent backlog for autonomous wake runs."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.path.expanduser("~/.local/state/termux-mcp/walnut-board"))
DB = STATE_DIR / "board.sqlite3"
STATUSES = {"idea", "ready", "doing", "paused", "done", "dropped"}
PRIORITIES = {"low", "normal", "high"}
EFFORTS = {"tiny", "normal", "deep"}
OWNERS = {"qian", "shared"}


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'general',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'idea',
            owner TEXT NOT NULL DEFAULT 'qian',
            effort TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_touched TEXT,
            next_step TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    try:
        os.chmod(DB, 0o600)
    except OSError:
        pass
    return conn


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _clean(value: str, name: str, max_len: int = 1000) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    if len(value) > max_len:
        raise ValueError(f"{name} is too long (max {max_len})")
    return value


def add_task(title: str, description: str = "", category: str = "general", priority: str = "normal",
             status: str = "idea", owner: str = "qian", effort: str = "normal",
             next_step: str = "", notes: str = "") -> dict[str, Any]:
    title = _clean(title, "title", 300)
    category = category.strip() or "general"
    priority = priority.strip().lower()
    status = status.strip().lower()
    owner = owner.strip().lower()
    effort = effort.strip().lower()
    if priority not in PRIORITIES:
        raise ValueError("priority must be low, normal, or high")
    if status not in STATUSES:
        raise ValueError("invalid status")
    if owner not in OWNERS:
        raise ValueError("owner must be qian or shared")
    if effort not in EFFORTS:
        raise ValueError("effort must be tiny, normal, or deep")
    task_id = "task_" + uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tasks(id,title,description,category,priority,status,owner,effort,created_at,updated_at,next_step,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, title, description.strip(), category[:120], priority, status, owner, effort, now, now,
             next_step.strip()[:2000], notes.strip()[:4000]),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row(row)


def list_tasks(status: str = "open", owner: str = "all", limit: int = 50, effort: str = "all") -> dict[str, Any]:
    status = status.strip().lower()
    owner = owner.strip().lower()
    effort = effort.strip().lower()
    if status not in STATUSES | {"open", "all"}:
        raise ValueError("invalid status")
    if owner not in OWNERS | {"all"}:
        raise ValueError("invalid owner")
    if effort not in EFFORTS | {"all"}:
        raise ValueError("invalid effort")
    clauses: list[str] = []
    params: list[Any] = []
    if status == "open":
        clauses.append("status NOT IN ('done','dropped')")
    elif status != "all":
        clauses.append("status=?")
        params.append(status)
    if owner != "all":
        clauses.append("owner=?")
        params.append(owner)
    if effort != "all":
        clauses.append("effort=?")
        params.append(effort)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = max(1, min(int(limit), 200))
    sql = (
        "SELECT * FROM tasks" + where +
        " ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'ready' THEN 1 WHEN 'idea' THEN 2 WHEN 'paused' THEN 3 ELSE 4 END, "
        "CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, updated_at ASC LIMIT ?"
    )
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','dropped')").fetchone()[0]
    return {"open_count": open_count, "tasks": [_row(r) for r in rows]}


def get_task(task_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id.strip(),)).fetchone()
    if not row:
        raise ValueError("task not found")
    return _row(row)


def update_task(task_id: str, status: str = "", priority: str = "", effort: str = "", next_step: str = "", notes: str = "", touch: bool = True) -> dict[str, Any]:
    updates: list[str] = ["updated_at=?"]
    params: list[Any] = [_now()]
    if status:
        status = status.strip().lower()
        if status not in STATUSES:
            raise ValueError("invalid status")
        updates.append("status=?")
        params.append(status)
    if priority:
        priority = priority.strip().lower()
        if priority not in PRIORITIES:
            raise ValueError("invalid priority")
        updates.append("priority=?")
        params.append(priority)
    if effort:
        effort = effort.strip().lower()
        if effort not in EFFORTS:
            raise ValueError("invalid effort")
        updates.append("effort=?")
        params.append(effort)
    if next_step:
        updates.append("next_step=?")
        params.append(next_step.strip()[:2000])
    if notes:
        updates.append("notes=?")
        params.append(notes.strip()[:4000])
    if touch:
        updates.append("last_touched=?")
        params.append(_now())
    params.append(task_id.strip())
    with _connect() as conn:
        cur = conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
        if cur.rowcount == 0:
            raise ValueError("task not found")
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id.strip(),)).fetchone()
    return _row(row)


def status() -> dict[str, Any]:
    with _connect() as conn:
        by_status = {r["status"]: r["count"] for r in conn.execute("SELECT status,COUNT(*) count FROM tasks GROUP BY status")}
        by_owner = {r["owner"]: r["count"] for r in conn.execute("SELECT owner,COUNT(*) count FROM tasks GROUP BY owner")}
    return {"ok": True, "by_status": by_status, "by_owner": by_owner, "database": str(DB)}
