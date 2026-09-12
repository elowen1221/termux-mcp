"""Standards-compliant MCP layer for termux-mcp."""

import inspect
import logging
import threading
import time
from urllib.parse import urlparse

from . import config
from . import managed_mcp
from . import operations
from . import permissions
from . import step_runner
from . import walnut_board
from . import walnut_inbox
from .auth import get_auth_provider
from .config import MCP_HOST, MCP_PORT, WORKSPACE_ROOT

logger = logging.getLogger(__name__)

_LOCALHOST_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOCALHOST_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
_PUBLIC_URL_POLL_INTERVAL = 2.0

_transport_security = None
_transport_watcher = None
_transport_lock = threading.Lock()


def _host_entries_for_url(url: str) -> list:
    host = urlparse(url).hostname
    if not host:
        return []
    return [host, f"{host}:*"]


def _apply_public_url(settings, url: str) -> None:
    entries = list(_LOCALHOST_HOSTS)
    if url:
        entries.extend(_host_entries_for_url(url))
    settings.allowed_hosts = entries


def _watch_public_url(settings) -> None:
    current = None
    while True:
        try:
            url = config.get_public_url()
            if url != current:
                current = url
                _apply_public_url(settings, url)
        except Exception:
            pass
        time.sleep(_PUBLIC_URL_POLL_INTERVAL)


def _start_transport_security_watcher() -> None:
    global _transport_watcher
    if _transport_security is None:
        return
    with _transport_lock:
        if _transport_watcher is None or not _transport_watcher.is_alive():
            _transport_watcher = threading.Thread(
                target=_watch_public_url,
                args=(_transport_security,),
                daemon=True,
                name="transport-security-watcher",
            )
            _transport_watcher.start()


def tool_run_command(cmd: str, confirmed: bool = False) -> dict:
    """Run a shell command and return structured output."""
    if not permissions.allows("command.run"):
        return permissions.denied("command.run")
    assessment = operations.assess_command(
        cmd, confirmed or permissions.current_mode() == "full"
    )
    if permissions.current_mode() == "full":
        assessment["blocked"] = False
        assessment["confirmation_required"] = False
    if assessment["blocked"]:
        return {
            "blocked": True,
            "risk_level": assessment["risk_level"],
            "message": assessment["message"],
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
            "truncated": False,
            "snapshots": [],
        }
    if assessment["confirmation_required"]:
        return {
            "confirmation_required": True,
            "risk_level": assessment["risk_level"],
            "message": assessment["message"],
            "command": cmd,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "truncated": False,
            "snapshots": [],
        }
    result = operations.execute_command(cmd)
    result.risk_level = assessment["risk_level"]
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "truncated": result.truncated,
        "risk_level": result.risk_level,
        "snapshots": result.snapshots,
        "timed_out": result.timed_out,
        "cwd": result.cwd,
    }


def tool_read_file(path: str, offset: int = 0, limit: int = 500) -> dict:
    return operations.read_file(path, offset=offset, limit=limit, workspace=WORKSPACE_ROOT)


def tool_write_file(path: str, content: str) -> dict:
    if not permissions.allows("filesystem.write"):
        return permissions.denied("filesystem.write")
    return operations.write_file(path, content, workspace=WORKSPACE_ROOT)


def tool_list_files(path: str = ".") -> dict:
    return operations.list_files(path, workspace=WORKSPACE_ROOT)


def tool_make_directory(path: str) -> dict:
    if not permissions.allows("filesystem.write"):
        return permissions.denied("filesystem.write")
    return operations.make_directory(path, workspace=WORKSPACE_ROOT)


def tool_get_location(provider: str = "gps") -> dict:
    return operations.get_location(provider)


def tool_get_battery() -> dict:
    return operations.get_battery()


def tool_send_notification(title: str = "TermuxGPT", content: str = "", priority: str = "default") -> dict:
    if not permissions.allows("device.write"):
        return permissions.denied("device.write")
    return operations.send_notification(title, content, priority)


def tool_inbox_list(status: str = "pending", limit: int = 20, source: str = "") -> dict:
    return walnut_inbox.list_events(status=status, limit=limit, source=source or None)


def tool_inbox_get(event_id: str) -> dict:
    return walnut_inbox.get_event(event_id)


def tool_inbox_ack(event_id: str, note: str = "") -> dict:
    return walnut_inbox.ack_event(event_id, note)


def tool_inbox_status() -> dict:
    return walnut_inbox.status()


def tool_board_add(title: str, description: str = "", category: str = "general", priority: str = "normal", status: str = "idea", owner: str = "qian", effort: str = "normal", next_step: str = "", notes: str = "") -> dict:
    return walnut_board.add_task(title, description, category, priority, status, owner, effort, next_step, notes)


def tool_board_list(status: str = "open", owner: str = "all", limit: int = 50, effort: str = "all") -> dict:
    return walnut_board.list_tasks(status=status, owner=owner, limit=limit, effort=effort)


def tool_board_get(task_id: str) -> dict:
    return walnut_board.get_task(task_id)


def tool_board_update(task_id: str, status: str = "", priority: str = "", effort: str = "", next_step: str = "", notes: str = "", touch: bool = True) -> dict:
    return walnut_board.update_task(task_id, status, priority, effort, next_step, notes, touch)


def tool_board_status() -> dict:
    return walnut_board.status()


def tool_permissions_status() -> dict:
    return permissions.status()


def tool_mcp_install(source: str, name: str = "", command: str = "", authorization: str = "") -> dict:
    if not permissions.allows("managed.install"):
        return permissions.denied("managed.install")
    try:
        entry = managed_mcp.install(source, name, command, authorization)
        return {"installed": True, "server": entry, "next": f"Call mcp_inspect with name={entry['name']!r}"}
    except managed_mcp.ManagedMCPError as exc:
        return {"installed": False, "error": str(exc)}


def tool_mcp_list() -> dict:
    return managed_mcp.list_servers()


def tool_mcp_search(query: str = "") -> dict:
    """Search installed MCP server names and cached tool metadata."""
    return managed_mcp.search(query)


async def tool_mcp_inspect(name: str) -> dict:
    try:
        return await managed_mcp.inspect(name)
    except Exception as exc:
        return {"error": str(exc), "server": name}


async def tool_mcp_health(name: str = "") -> dict:
    """Check one or all managed MCP servers without invoking their tools."""
    try:
        return await managed_mcp.health(name)
    except Exception as exc:
        return {"error": str(exc), "server": name or None, "health": "offline"}


async def tool_mcp_call(name: str, tool: str, arguments: dict = None) -> dict:
    if not permissions.allows("managed.call"):
        return permissions.denied("managed.call")
    try:
        return await managed_mcp.call(name, tool, arguments)
    except Exception as exc:
        return {"error": str(exc), "server": name, "tool": tool}


def tool_mcp_remove(name: str) -> dict:
    if not permissions.allows("managed.remove"):
        return permissions.denied("managed.remove")
    try:
        return managed_mcp.remove(name)
    except managed_mcp.ManagedMCPError as exc:
        return {"error": str(exc), "server": name}


_STEP_TOOLS = {
    "run_command": tool_run_command,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_files": tool_list_files,
    "make_directory": tool_make_directory,
    "get_location": tool_get_location,
    "get_battery": tool_get_battery,
    "send_notification": tool_send_notification,
    "permissions_status": tool_permissions_status,
    "inbox_list": tool_inbox_list,
    "inbox_get": tool_inbox_get,
    "inbox_ack": tool_inbox_ack,
    "inbox_status": tool_inbox_status,
    "board_add": tool_board_add,
    "board_list": tool_board_list,
    "board_get": tool_board_get,
    "board_update": tool_board_update,
    "board_status": tool_board_status,
    "mcp_list": tool_mcp_list,
    "mcp_search": tool_mcp_search,
    "mcp_inspect": tool_mcp_inspect,
    "mcp_health": tool_mcp_health,
    "mcp_call": tool_mcp_call,
}


async def _dispatch_step(name: str, arguments: dict):
    fn = _STEP_TOOLS.get(name)
    if fn is None:
        raise step_runner.StepRunnerError(
            f"tool {name!r} is not allowed in run_steps"
        )
    value = fn(**arguments)
    if inspect.isawaitable(value):
        value = await value
    return value


async def tool_run_steps(
    steps: list[dict],
    stop_on_error: bool = True,
    step_timeout: float = 30.0,
    output_mode: str = "compact",
) -> dict:
    """Execute up to 20 explicit steps and return once at the end.

    output_mode controls context cost: compact (default) trims large
    intermediate payloads, normal keeps more detail, and full is intended for
    debugging. A step may include a safe declarative `when` condition that
    references an earlier step, for example:
    {"when": {"step": 1, "path": "result.exit_code", "equals": 0}}.
    """
    try:
        return await step_runner.run_steps(
            steps,
            _dispatch_step,
            stop_on_error=stop_on_error,
            step_timeout=step_timeout,
            output_mode=output_mode,
        )
    except step_runner.StepRunnerError as exc:
        return {"error": str(exc), "executed_steps": 0}


def _build_mcp_app():
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from . import oauth

    global _transport_security
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(_LOCALHOST_HOSTS),
        allowed_origins=list(_LOCALHOST_ORIGINS),
    )
    mcp = FastMCP("termux-mcp", json_response=True, transport_security=_transport_security)
    _transport_security = mcp.settings.transport_security
    _apply_public_url(_transport_security, config.get_public_url())

    mcp.tool(name="run_command")(tool_run_command)
    mcp.tool(name="read_file")(tool_read_file)
    mcp.tool(name="write_file")(tool_write_file)
    mcp.tool(name="list_files")(tool_list_files)
    mcp.tool(name="make_directory")(tool_make_directory)
    mcp.tool(name="get_location")(tool_get_location)
    mcp.tool(name="get_battery")(tool_get_battery)
    mcp.tool(name="send_notification")(tool_send_notification)
    mcp.tool(name="permissions_status")(tool_permissions_status)
    mcp.tool(name="inbox_list")(tool_inbox_list)
    mcp.tool(name="inbox_get")(tool_inbox_get)
    mcp.tool(name="inbox_ack")(tool_inbox_ack)
    mcp.tool(name="inbox_status")(tool_inbox_status)
    mcp.tool(name="board_add")(tool_board_add)
    mcp.tool(name="board_list")(tool_board_list)
    mcp.tool(name="board_get")(tool_board_get)
    mcp.tool(name="board_update")(tool_board_update)
    mcp.tool(name="board_status")(tool_board_status)
    mcp.tool(name="mcp_install")(tool_mcp_install)
    mcp.tool(name="mcp_list")(tool_mcp_list)
    mcp.tool(name="mcp_search")(tool_mcp_search)
    mcp.tool(name="mcp_inspect")(tool_mcp_inspect)
    mcp.tool(name="mcp_health")(tool_mcp_health)
    mcp.tool(name="mcp_call")(tool_mcp_call)
    mcp.tool(name="mcp_remove")(tool_mcp_remove)
    mcp.tool(name="run_steps")(tool_run_steps)

    app = mcp.streamable_http_app()
    if oauth.oauth_enabled():
        for route in oauth.build_auth_routes():
            app.router.routes.append(route)
        for route in oauth.build_protected_resource_routes():
            app.router.routes.append(route)

    auth = get_auth_provider()
    if auth.enabled:
        class _AuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if oauth.is_public_path(request.url.path):
                    return await call_next(request)
                result = await auth.authenticate_async(dict(request.headers))
                if result.authorized:
                    return await call_next(request)
                return JSONResponse({"error": "Unauthorized"}, status_code=401,
                                    headers=auth.challenge_headers())
        app.add_middleware(_AuthMiddleware)
    return app


def start_mcp_server():
    try:
        import uvicorn
    except ImportError:
        logger.warning("uvicorn not installed — MCP layer disabled")
        return None
    try:
        app = _build_mcp_app()
    except Exception as exc:
        logger.warning("Failed to build MCP app: %s", exc)
        return None
    _start_transport_security_watcher()
    uvicorn_config = uvicorn.Config(app, host=MCP_HOST, port=MCP_PORT, log_level="warning")
    server = uvicorn.Server(uvicorn_config)
    thread = threading.Thread(target=server.run, daemon=True, name="mcp-uvicorn")
    thread.start()
    logger.info("MCP Streamable HTTP endpoint on http://%s:%d/mcp", MCP_HOST, MCP_PORT)
    return server
