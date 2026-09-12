"""Process management for the termux-mcp launcher.

State lives under ~/.local/state/termux-mcp/ (XDG-style):
  server.pid   — PID of the running `python -m termux_mcp` server
  tunnel.pid   — PID of the active tunnel process (if any)
  server.log   — captured stdout/stderr of the server
  tunnel.log   — captured stdout/stderr of the tunnel process

The launcher never uses bare `&` backgrounding: every child is tracked by
PID file, and stop/restart/status operate on those PIDs.
"""

import os
import signal
import subprocess
import sys
import time
from typing import Optional

from .config import STATE_DIR

# State lives under the profile-aware XDG-style state dir
# (~/.local/state/termux-mcp[-<profile>]/):
#   server.pid   — PID of the running `python -m termux_mcp` server
#   tunnel.pid   — PID of the active tunnel process (if any)
#   server.log   — captured stdout/stderr of the server
#   tunnel.log   — captured stdout/stderr of the tunnel process

PID_FILE: str = os.path.join(STATE_DIR, "server.pid")
TUNNEL_PID_FILE: str = os.path.join(STATE_DIR, "tunnel.pid")
LOG_FILE: str = os.path.join(STATE_DIR, "server.log")
TUNNEL_LOG_FILE: str = os.path.join(STATE_DIR, "tunnel.log")


def state_dir() -> str:
    return STATE_DIR


def pid_file() -> str:
    return PID_FILE


def tunnel_pid_file() -> str:
    return TUNNEL_PID_FILE


def log_file() -> str:
    return LOG_FILE


def tunnel_log_file() -> str:
    return TUNNEL_LOG_FILE


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        # Windows: os.kill(pid, 0) is unsupported — probe via OpenProcess.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    # Reap the process when the caller is also its parent (notably tests and
    # embedded launchers). A normal later CLI invocation is not the parent and
    # receives ChildProcessError, then falls through to the portable probes.
    try:
        waited_pid, _ = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except ChildProcessError:
        pass
    # kill(pid, 0) succeeds for a terminated child that is waiting to be
    # reaped. Treat that zombie as stopped instead of reporting a phantom
    # live server in status/restart and long-running test parents.
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as stat_file:
            fields = stat_file.read().split()
        if len(fields) >= 3 and fields[2] == "Z":
            return False
    except OSError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def read_pid() -> Optional[int]:
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def write_pid(pid: int) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))


def clear_pid() -> None:
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def read_tunnel_pid() -> Optional[int]:
    try:
        with open(TUNNEL_PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def write_tunnel_pid(pid: Optional[int]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    if pid:
        with open(TUNNEL_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))
    else:
        clear_tunnel_pid()


def clear_tunnel_pid() -> None:
    try:
        os.remove(TUNNEL_PID_FILE)
    except OSError:
        pass


def is_running() -> bool:
    """True when the server PID file points at a live process.

    A stale PID file (process already dead) is cleaned up so status/start
    never report a phantom running server.
    """
    pid = read_pid()
    if not pid:
        return False
    if _pid_alive(pid):
        return True
    clear_pid()
    return False


def tunnel_is_running() -> bool:
    """True when the tunnel PID file points at a live process.

    A stale tunnel.pid (process already dead) is cleaned up so status/stop
    never report a phantom running tunnel.
    """
    pid = read_tunnel_pid()
    if not pid:
        return False
    if _pid_alive(pid):
        return True
    clear_tunnel_pid()
    return False


def kill_pid(pid: Optional[int], timeout: float = 5.0) -> bool:
    """Terminate a process by PID (SIGTERM, then force-kill).

    On Windows, os.kill() can transiently fail with access-denied while the
    target process is still initializing, so the SIGTERM is retried and a
    `taskkill /F` fallback is used if the process survives.
    """
    if not pid or not _pid_alive(pid):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, signal.SIGTERM)
            break
        except OSError:
            time.sleep(0.2)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    # Force kill. SIGKILL is POSIX-only; on Windows use taskkill /F, which
    # is more reliable than os.kill for processes stuck in early startup.
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, AttributeError):
            pass
    return not _pid_alive(pid)


def start_server(env: Optional[dict] = None) -> int:
    """Start the termux-mcp server as a detached child process.

    Returns the child PID. Raises RuntimeError if already running.
    """
    if is_running():
        raise RuntimeError(
            f"termux-mcp is already running (pid {read_pid()}). "
            "Use 'termux-mcp status' or 'termux-mcp restart'."
        )
    os.makedirs(STATE_DIR, exist_ok=True)
    log_f = open(LOG_FILE, "ab")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child_env = dict(env or os.environ.copy())
    # Tool subprocesses carry this marker so recursive health checks can be
    # skipped. Never leak it into the long-lived server process itself.
    child_env.pop("TERMUX_MCP_TOOL_CONTEXT", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "termux_mcp"],
        cwd=repo_root,
        env=child_env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    write_pid(proc.pid)
    return proc.pid


def schedule_server_restart(old_pid: int, delay: float = 0.75) -> int:
    """Schedule a detached server-only restart and return the worker PID.

    Used when `termux-mcp restart` is invoked through MCP itself: a
    synchronous self-kill would tear down the request before the replacement
    server can be launched.
    """
    if old_pid <= 0:
        raise ValueError("old_pid must be positive")
    os.makedirs(STATE_DIR, exist_ok=True)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    worker_env = os.environ.copy()
    worker_env.pop("TERMUX_MCP_TOOL_CONTEXT", None)
    worker_env["TERMUX_MCP_RESTART_PID"] = str(old_pid)
    worker_env["TERMUX_MCP_RESTART_DELAY"] = str(max(0.1, delay))
    code = (
        "import os,time\n"
        "from termux_mcp import process\n"
        "from termux_mcp.config import PORT,MCP_PORT,AUTH_TOKEN,MCP_ENABLED\n"
        "old=int(os.environ['TERMUX_MCP_RESTART_PID'])\n"
        "time.sleep(float(os.environ.get('TERMUX_MCP_RESTART_DELAY','0.75')))\n"
        "if process._pid_alive(old): process.kill_pid(old, timeout=10.0)\n"
        "if process.read_pid()==old: process.clear_pid()\n"
        "process.start_server()\n"
        "rest=process.wait_http(PORT, timeout=15.0)\n"
        "mcp=(process.wait_mcp_initialize(MCP_PORT, AUTH_TOKEN, timeout=15.0)[0] if MCP_ENABLED else True)\n"
        "raise SystemExit(0 if (rest and mcp) else 2)\n"
    )
    log_f = open(LOG_FILE, "ab")
    worker = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=worker_env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return worker.pid


def stop_server(timeout: float = 10.0) -> bool:
    """Stop the running server. Returns True if it was stopped."""
    pid = read_pid()
    if not pid:
        return False
    stopped = kill_pid(pid, timeout)
    if not stopped:
        # Grace period: a process in the final termination window can still
        # report alive for a moment after being killed.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if not _pid_alive(pid):
                stopped = True
                break
            time.sleep(0.2)
    if stopped or not _pid_alive(pid):
        clear_pid()
    return stopped


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check whether a TCP port is accepting connections."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def mcp_initialize_probe(port: int, token: str = "", timeout: float = 5.0) -> tuple[bool, str]:
    """Perform a real local MCP initialize request without proxy handling.

    urllib inherits HTTP(S)_PROXY environment variables, which is undesirable
    for a loopback health check and can make a healthy local MCP endpoint look
    timed out.  http.client talks directly to 127.0.0.1.
    """
    import http.client
    import json

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "termux-mcp-health", "version": "1"},
        },
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Content-Length": str(len(payload)),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", "/mcp", body=payload, headers=headers)
        response = conn.getresponse()
        body = response.read(65536).decode("utf-8", errors="replace")
        if response.status != 200:
            return False, f"HTTP {response.status}"
        parsed = json.loads(body)
        result = parsed.get("result", {}) if isinstance(parsed, dict) else {}
        if not result.get("protocolVersion"):
            return False, "HTTP 200 but initialize result missing"
        return True, f"initialize OK ({result['protocolVersion']})"
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def wait_mcp_initialize(port: int, token: str = "", timeout: float = 15.0) -> tuple[bool, str]:
    """Wait until MCP initialize succeeds, bounded by a hard deadline."""
    deadline = time.monotonic() + timeout
    detail = "not attempted"
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ok, detail = mcp_initialize_probe(port, token, timeout=min(2.0, max(0.2, remaining)))
        if ok:
            return True, detail
        time.sleep(min(0.3, max(0.05, deadline - time.monotonic())))
    return False, detail


def wait_http(port: int, timeout: float = 15.0) -> bool:
    """Wait until the port accepts connections (server warm-up)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.3)
    return False


def tail_log(n: int = 50) -> str:
    """Return the last n lines of the server log."""
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except OSError:
        return ""


def tail_tunnel_log(n: int = 50) -> str:
    """Return the last n lines of the tunnel log."""
    try:
        with open(TUNNEL_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except OSError:
        return ""
