"""Standards-compliant MCP layer for termux-mcp."""

import inspect
import logging
import threading
import time
from urllib.parse import urlparse

from . import config
from . import managed_mcp
from . import operations
from . import android_bridge
from . import permissions
from . import step_runner
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


def tool_permissions_status() -> dict:
    return permissions.status()


def tool_android_status() -> dict:
    """Report whether the optional Shizuku/rish Android bridge is ready."""
    return android_bridge.status()


def tool_android_list_apps(filter: str = "", third_party_only: bool = True) -> dict:
    """List Android packages through the configured Shizuku/rish bridge."""
    return android_bridge.list_apps(filter, third_party_only)


def tool_android_find_app(query: str) -> dict:
    """Find Android package ids by a package-name fragment."""
    return android_bridge.find_app(query)


def tool_android_open_app(package: str) -> dict:
    """Open one Android package by resolving its launcher activity."""
    if not permissions.allows("device.write"):
        return permissions.denied("device.write")
    return android_bridge.open_app(package)


def tool_android_current_ui(max_depth: int = 6) -> dict:
    """Read a compact accessibility tree from the active Android window."""
    return android_bridge.current_ui(max_depth)

def tool_android_screenshot():
    """Capture the current Android screen through AccessibilityService."""
    data = android_bridge.screenshot_png()
    if not data:
        return {"ok": False, "error": "screenshot unavailable"}
    return Image(data=data, format="png")

def tool_android_click(text: str) -> dict:
    """Click a currently visible Android node by text, re-resolving it before action."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.click(text)

def tool_android_tap(x: float, y: float) -> dict:
    """Tap absolute screen coordinates through AccessibilityService."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.tap(x, y)

def tool_android_click_verify(text: str, expect_text: str, timeout_ms: int = 2000) -> dict:
    """Click visible text and verify that expected text appears afterwards."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.click_and_verify(text, expect_text, timeout_ms)

def tool_android_type(text: str) -> dict:
    """Replace text in the currently focused editable Android node."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.type_text(text)

def tool_android_swipe(x1: float, y1: float, x2: float, y2: float, duration: int = 300) -> dict:
    """Dispatch an Android accessibility swipe gesture."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.swipe(x1, y1, x2, y2, duration)

def tool_android_back() -> dict:
    """Perform Android's global Back action through AccessibilityService."""
    if not permissions.allows("device.write"): return permissions.denied("device.write")
    return android_bridge.back()


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
    "android_status": tool_android_status,
    "android_list_apps": tool_android_list_apps,
    "android_find_app": tool_android_find_app,
    "android_open_app": tool_android_open_app,
    "android_current_ui": tool_android_current_ui,
    "android_screenshot": tool_android_screenshot,
    "android_click": tool_android_click,
    "android_tap": tool_android_tap,
    "android_click_verify": tool_android_click_verify,
    "android_type": tool_android_type,
    "android_swipe": tool_android_swipe,
    "android_back": tool_android_back,
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
    from mcp.server.fastmcp import FastMCP, Image
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
    mcp.tool(name="android_status")(tool_android_status)
    mcp.tool(name="android_list_apps")(tool_android_list_apps)
    mcp.tool(name="android_find_app")(tool_android_find_app)
    mcp.tool(name="android_open_app")(tool_android_open_app)
    mcp.tool(name="android_current_ui")(tool_android_current_ui)
    mcp.tool(name="android_screenshot")(tool_android_screenshot)
    mcp.tool(name="android_click")(tool_android_click)
    mcp.tool(name="android_tap")(tool_android_tap)
    mcp.tool(name="android_click_verify")(tool_android_click_verify)
    mcp.tool(name="android_type")(tool_android_type)
    mcp.tool(name="android_swipe")(tool_android_swipe)
    mcp.tool(name="android_back")(tool_android_back)
    mcp.tool(name="mcp_install")(tool_mcp_install)
    mcp.tool(name="mcp_list")(tool_mcp_list)
    mcp.tool(name="mcp_search")(tool_mcp_search)
    mcp.tool(name="mcp_inspect")(tool_mcp_inspect)
    mcp.tool(name="mcp_health")(tool_mcp_health)
    mcp.tool(name="mcp_call")(tool_mcp_call)
    mcp.tool(name="mcp_remove")(tool_mcp_remove)
    mcp.tool(name="run_steps")(tool_run_steps)

    from . import extensions
    extensions.register_local_extensions(mcp, _STEP_TOOLS)

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
