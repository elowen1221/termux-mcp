"""Resilience helpers for managed MCP discovery.

Keeps a small last-known-good tool catalogue on disk so a transient tunnel or
child-server failure does not make an installed MCP disappear from discovery.
The cache contains tool metadata only; credentials are never written here.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import CONFIG_DIR

CACHE_FILE = Path(CONFIG_DIR) / "managed_mcp_tools.json"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2


def _load() -> dict[str, Any]:
    try:
        value = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(value: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(CACHE_FILE)


def remember(name: str, transport: str, tools: list[dict[str, str]]) -> None:
    cache = _load()
    cache[name] = {
        "name": name,
        "transport": transport,
        "tools": tools,
        "count": len(tools),
        "last_success": int(time.time()),
    }
    _save(cache)


def cached(name: str) -> dict[str, Any] | None:
    value = _load().get(name)
    return value if isinstance(value, dict) else None


def forget(name: str) -> None:
    cache = _load()
    if name in cache:
        del cache[name]
        _save(cache)


def search(query: str, installed: list[dict[str, Any]]) -> dict[str, Any]:
    """Search installed server names and last-known-good tool metadata."""
    needle = query.strip().casefold()
    cache = _load()
    matches = []
    for server in installed:
        name = str(server.get("name", ""))
        snapshot = cache.get(name, {}) if isinstance(cache.get(name, {}), dict) else {}
        tools = snapshot.get("tools", []) if isinstance(snapshot.get("tools", []), list) else []
        server_hit = not needle or needle in name.casefold() or needle in str(server.get("source", "")).casefold()
        if server_hit:
            matches.append({
                "server": name,
                "tool": None,
                "description": "",
                "transport": server.get("transport"),
                "last_success": snapshot.get("last_success"),
            })
        for tool in tools:
            tool_name = str(tool.get("name", ""))
            description = str(tool.get("description", ""))
            if not needle or needle in tool_name.casefold() or needle in description.casefold():
                matches.append({
                    "server": name,
                    "tool": tool_name,
                    "description": description,
                    "transport": server.get("transport"),
                    "last_success": snapshot.get("last_success"),
                })
    return {"query": query, "matches": matches, "count": len(matches)}


async def retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> tuple[Any | None, Exception | None, int]:
    """Run an idempotent discovery operation with bounded retry/backoff."""
    last_error = None
    attempts = 0
    for attempt in range(retries + 1):
        attempts += 1
        try:
            return await asyncio.wait_for(operation(), timeout=timeout), None, attempts
        except Exception as exc:  # caller decides whether stale cache is acceptable
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(0.35 * (2 ** attempt))
    return None, last_error, attempts
