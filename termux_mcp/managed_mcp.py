"""Install and operate third-party MCP servers behind one Termux gateway."""

import json
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import CONFIG_DIR, HOME
from . import managed_resilience

REGISTRY_FILE = Path(CONFIG_DIR) / "managed_mcp.json"
MANAGED_ROOT = Path(HOME) / ".local" / "share" / "termux-mcp" / "servers"
_LOCK = threading.Lock()
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")


class ManagedMCPError(RuntimeError):
    pass


def _load_registry() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_registry(registry: dict[str, dict[str, Any]]) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(REGISTRY_FILE)


def _default_name(source: str) -> str:
    parsed = urlparse(source)
    raw = Path(parsed.path.rstrip("/")).name or parsed.hostname or "server"
    raw = raw.removesuffix(".git")
    value = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")
    return (value or "server")[:48]


def _validated_name(name: str) -> str:
    value = name.strip().lower()
    if not _NAME_RE.fullmatch(value):
        raise ManagedMCPError("name must use 1-48 lowercase letters, digits, underscores, or hyphens")
    return value


def _run(argv: list[str], cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(argv, cwd=str(cwd) if cwd else None, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=None, check=False)
    except OSError as exc:
        raise ManagedMCPError(f"could not run {argv[0]}: {exc}") from exc
    output = completed.stdout or ""
    if completed.returncode:
        tail = "\n".join(output.splitlines()[-30:])
        raise ManagedMCPError(f"command failed ({completed.returncode}): {' '.join(argv)}\n{tail}")
    return output


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, ValueError) as exc:
        raise ManagedMCPError(f"invalid pyproject.toml: {exc}") from exc


def _install_python(source_dir: Path) -> tuple[list[str], str]:
    environment = source_dir.parent / "venv"
    _run([sys.executable, "-m", "venv", str(environment)])
    python = environment / "bin" / "python"
    _run([str(python), "-m", "pip", "install", "."], cwd=source_dir)
    data = _read_toml(source_dir / "pyproject.toml")
    scripts = data.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict) and scripts:
        return [str(environment / "bin" / next(iter(scripts)))], "python"
    for candidate in ("server.py", "main.py", "app.py"):
        if (source_dir / candidate).is_file():
            return [str(python), candidate], "python"
    raise ManagedMCPError("Python project installed, but no project script/server.py/main.py was found; retry with an explicit command")


def _install_node(source_dir: Path) -> tuple[list[str], str]:
    if shutil.which("npm") is None:
        raise ManagedMCPError("Node.js is required; install it with: pkg install nodejs")
    try:
        package = json.loads((source_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManagedMCPError(f"invalid package.json: {exc}") from exc
    _run(["npm", "install"], cwd=source_dir)
    scripts = package.get("scripts") or {}
    if "build" in scripts:
        _run(["npm", "run", "build"], cwd=source_dir)
    binary = package.get("bin")
    if isinstance(binary, dict) and binary:
        binary = next(iter(binary.values()))
    if isinstance(binary, str):
        return ["node", binary], "node"
    if "start" in scripts:
        return ["npm", "run", "start", "--"], "node"
    for candidate in (package.get("main"), "dist/index.js", "build/index.js", "index.js"):
        if candidate and (source_dir / candidate).is_file():
            return ["node", str(candidate)], "node"
    raise ManagedMCPError("Node project installed, but no bin/start/main entry was found; retry with an explicit command")


def _github_repo(source: str) -> str | None:
    parsed = urlparse(source)
    if parsed.scheme not in ("https", "http") or parsed.hostname != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ManagedMCPError("use a GitHub repository URL like https://github.com/owner/repo")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"


def install(source: str, name: str = "", command: str = "", authorization: str = "") -> dict[str, Any]:
    source = source.strip()
    if not source:
        raise ManagedMCPError("source URL is required")
    parsed = urlparse(source)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ManagedMCPError("source must be an http(s) MCP or GitHub URL")
    server_name = _validated_name(name or _default_name(source))
    with _LOCK:
        registry = _load_registry()
        if server_name in registry:
            raise ManagedMCPError(f"{server_name!r} already exists; remove it or choose another name")
        github = _github_repo(source)
        if github is None:
            entry = {"name": server_name, "source": source, "transport": "http", "url": source,
                     "authorization": authorization.strip(), "installed_at": int(time.time())}
        else:
            server_root = MANAGED_ROOT / server_name
            source_dir = server_root / "source"
            if server_root.exists():
                raise ManagedMCPError(f"managed directory already exists: {server_root}")
            server_root.mkdir(parents=True)
            try:
                _run(["git", "clone", "--depth", "1", github, str(source_dir)])
                if command:
                    argv = shlex.split(command)
                    if not argv:
                        raise ManagedMCPError("explicit command is empty")
                    runtime = "custom"
                elif (source_dir / "pyproject.toml").is_file():
                    argv, runtime = _install_python(source_dir)
                elif (source_dir / "package.json").is_file():
                    argv, runtime = _install_node(source_dir)
                else:
                    raise ManagedMCPError("could not detect Python or Node project; retry with an explicit command")
            except Exception:
                shutil.rmtree(server_root, ignore_errors=True)
                raise
            entry = {"name": server_name, "source": source, "transport": "stdio", "command": argv,
                     "cwd": str(source_dir), "runtime": runtime, "installed_at": int(time.time())}
        registry[server_name] = entry
        _save_registry(registry)
    return _public_entry(entry)


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    clean = dict(entry)
    if clean.get("authorization"):
        clean["authorization"] = "configured"
    return clean


def list_servers() -> dict[str, Any]:
    registry = _load_registry()
    return {"servers": [_public_entry(registry[name]) for name in sorted(registry)], "count": len(registry)}


def search(query: str = "") -> dict[str, Any]:
    """Search installed MCPs plus the last-known-good catalogue of their tools."""
    return managed_resilience.search(query, list_servers()["servers"])


def _entry(name: str) -> dict[str, Any]:
    name = _validated_name(name)
    entry = _load_registry().get(name)
    if entry is None:
        raise ManagedMCPError(f"managed MCP {name!r} was not found")
    return entry


async def _session(entry: dict[str, Any], operation) -> Any:
    from mcp.client.session import ClientSession
    if entry["transport"] == "http":
        from mcp.client.streamable_http import streamablehttp_client
        headers = {}
        if entry.get("authorization"):
            value = entry["authorization"]
            headers["Authorization"] = value if value.lower().startswith("bearer ") else f"Bearer {value}"
        initialized = False
        try:
            async with (streamablehttp_client(entry["url"], headers=headers) as streams,
                        ClientSession(streams[0], streams[1]) as session):
                await session.initialize()
                initialized = True
                return await operation(session)
        except Exception as streamable_error:
            if initialized:
                raise
            try:
                from mcp.client.sse import sse_client
                async with (sse_client(entry["url"], headers=headers) as streams,
                            ClientSession(streams[0], streams[1]) as session):
                    await session.initialize()
                    return await operation(session)
            except Exception as sse_error:
                raise ManagedMCPError("remote MCP connection failed with Streamable HTTP and SSE: "
                                      f"{streamable_error}; {sse_error}") from sse_error
    from mcp.client.stdio import StdioServerParameters, stdio_client
    argv = entry["command"]
    params = StdioServerParameters(command=argv[0], args=argv[1:], cwd=entry["cwd"])
    async with (stdio_client(params) as streams, ClientSession(streams[0], streams[1]) as session):
        await session.initialize()
        return await operation(session)


async def inspect(name: str) -> dict[str, Any]:
    """Inspect with retry; fall back to last-known-good catalogue on transient failure."""
    entry = _entry(name)
    async def once():
        async def operation(session):
            result = await session.list_tools()
            tools = [{"name": tool.name, "description": tool.description or ""} for tool in result.tools]
            return {"name": entry["name"], "transport": entry["transport"], "tools": tools, "count": len(tools)}
        return await _session(entry, operation)
    result, error, attempts = await managed_resilience.retry(once)
    if result is not None:
        managed_resilience.remember(entry["name"], entry["transport"], result["tools"])
        result.update({"health": "online", "stale": False, "attempts": attempts})
        return result
    snapshot = managed_resilience.cached(entry["name"])
    if snapshot:
        return {**snapshot, "health": "degraded", "stale": True, "attempts": attempts,
                "error": str(error), "message": "live inspection failed; returning last-known-good tool catalogue"}
    raise ManagedMCPError(f"inspection failed after {attempts} attempts: {error}")


async def health(name: str = "") -> dict[str, Any]:
    """Check one or all managed MCPs using resilient inspection.

    `online` means a live catalogue was retrieved, `degraded` means the live
    check failed but a last-known-good catalogue is available, and `offline`
    means neither live inspection nor a cached catalogue was usable.
    """
    registry = _load_registry()
    if name:
        names = [_validated_name(name)]
        if names[0] not in registry:
            raise ManagedMCPError(f"managed MCP {names[0]!r} was not found")
    else:
        names = sorted(registry)

    checks = []
    for server_name in names:
        started = time.monotonic()
        try:
            result = await inspect(server_name)
            checks.append({
                "name": server_name,
                "health": result.get("health", "online"),
                "stale": bool(result.get("stale")),
                "tool_count": result.get("count", len(result.get("tools", []))),
                "attempts": result.get("attempts", 1),
                "latency_ms": round((time.monotonic() - started) * 1000),
                "error": result.get("error"),
            })
        except Exception as exc:
            checks.append({
                "name": server_name,
                "health": "offline",
                "stale": False,
                "tool_count": 0,
                "attempts": managed_resilience.DEFAULT_RETRIES + 1,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "error": str(exc),
            })

    counts = {"online": 0, "degraded": 0, "offline": 0}
    for item in checks:
        counts[item["health"]] = counts.get(item["health"], 0) + 1
    overall = "online"
    if counts["offline"]:
        overall = "offline" if counts["offline"] == len(checks) else "degraded"
    elif counts["degraded"]:
        overall = "degraded"
    if not checks:
        overall = "empty"
    return {"health": overall, "count": len(checks), "counts": counts, "servers": checks}


async def call(name: str, tool: str, arguments: dict[str, Any] | None = None) -> dict:
    """Call a tool once. Calls are never automatically replayed because they may have side effects."""
    entry = _entry(name)
    async def operation(session):
        result = await session.call_tool(tool, arguments or {})
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return {"result": str(result)}
    return await _session(entry, operation)


def remove(name: str) -> dict[str, Any]:
    name = _validated_name(name)
    with _LOCK:
        registry = _load_registry()
        entry = registry.pop(name, None)
        if entry is None:
            raise ManagedMCPError(f"managed MCP {name!r} was not found")
        recovered_to = ""
        server_root = MANAGED_ROOT / name
        if server_root.exists():
            trash = MANAGED_ROOT / ".trash"
            trash.mkdir(parents=True, exist_ok=True)
            destination = trash / f"{name}-{int(time.time())}"
            server_root.replace(destination)
            recovered_to = str(destination)
        _save_registry(registry)
        managed_resilience.forget(name)
    return {"removed": name, "recoverable_from": recovered_to or None}
