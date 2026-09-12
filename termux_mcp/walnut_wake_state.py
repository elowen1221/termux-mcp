"""Small local state store used to keep consecutive Walnut Wake runs from repeating themselves."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.path.expanduser("~/.local/state/termux-mcp/walnut-wake"))
STATE_FILE = STATE_DIR / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def update_state(activity: str = "", tools: list[str] | None = None,
                 touched_tasks: list[str] | None = None, note: str = "") -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass
    state = read_state()
    state["last_wake"] = _now()
    if activity.strip():
        state["last_activity"] = activity.strip()[:500]
    if tools is not None:
        state["recently_used_tools"] = [str(x)[:120] for x in tools][-10:]
    if touched_tasks is not None:
        state["recently_touched_tasks"] = [str(x)[:200] for x in touched_tasks][-10:]
    if note.strip():
        state["note"] = note.strip()[:1000]
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError:
        pass
    return state
