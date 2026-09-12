"""Shared business operations used by both the REST API and the MCP layer.

REST handlers and MCP tools call these same functions directly — the MCP
layer never proxies through the REST HTTP API.

Safety invariants preserved from the original REST implementation:
  * get_risk_assessment() gates every command (dangerous -> blocked).
  * Warning-level commands return a structured confirmation-required result.
  * Files are snapshotted before overwrite (snapshot-before-write).
  * Deletions move to trash instead of being destroyed.
  * Paths are resolved with realpath before workspace-boundary checks.
"""

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .config import COMMAND_TIMEOUT, HOME, MAX_OUTPUT_BYTES
from .safety import snapshot_before_write, snapshot_targets_from_command
from .security import get_risk_assessment
from .shell import (
    _spawn_auto_input,
    get_current_dir,
    handle_cd,
    preprocess,
    set_active_pid,
    shell_prefix,
)
from .utils import is_safe_path, shell_quote

TRUNCATION_MARKER = (
    f"\n[Output truncated: max {MAX_OUTPUT_BYTES} bytes — "
    f"full output not sent]\n"
)

# Stream callback signature: callable(line: str, is_stderr: bool) -> None
StreamFn = Callable[[str, bool], None]


@dataclass
class CommandResult:
    """Structured result of a shell command execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    risk_level: str = "safe"
    message: str = ""
    snapshots: List[str] = field(default_factory=list)
    blocked: bool = False
    confirmation_required: bool = False
    cwd: str = ""


# ── Path resolution ──────────────────────────────────────────────────────────

def resolve_path(path: str, workspace: Optional[str] = None) -> Optional[str]:
    """Resolve a path with realpath and enforce the workspace boundary.

    Returns the resolved absolute path, or None when the path is not
    allowed (unsafe system paths, or outside the optional workspace root).
    """
    if not path or not isinstance(path, str):
        return None
    try:
        expanded = os.path.expanduser(path)
        real = os.path.realpath(expanded)
    except (ValueError, OSError):
        return None
    if not is_safe_path(path):
        return None
    if workspace:
        ws_real = os.path.realpath(os.path.expanduser(workspace))
        if not (real == ws_real or real.startswith(ws_real + os.sep)):
            return None
    return real


# ── Command risk gating ──────────────────────────────────────────────────────

def assess_command(cmd: str, confirmed: bool = False) -> dict:
    """Risk-gate a command. Returns a dict with blocked/confirmation_required.

    Shared by the REST /run handler and the MCP run_command tool.
    """
    risk = get_risk_assessment(cmd)
    if risk["blocked"]:
        return {
            "blocked": True,
            "confirmation_required": False,
            "risk_level": risk["risk_level"],
            "message": risk["message"],
        }
    if risk["requires_confirmation"] and not confirmed:
        return {
            "blocked": False,
            "confirmation_required": True,
            "risk_level": risk["risk_level"],
            "message": risk["message"],
        }
    return {
        "blocked": False,
        "confirmation_required": False,
        "risk_level": risk["risk_level"],
        "message": risk["message"],
    }


# ── Command execution ────────────────────────────────────────────────────────

def execute_command(
    cmd: str,
    timeout: Optional[int] = None,
    max_output: Optional[int] = None,
    stream: Optional[StreamFn] = None,
) -> CommandResult:
    """Run a shell command and return a structured result.

    `stream` is an optional callback invoked with (line, is_stderr) for each
    output line as it is produced — the REST layer uses it for chunked
    streaming. When None, output is only captured.

    Files the command may overwrite are snapshotted before execution; the
    snapshot paths are returned in `result.snapshots`.
    """
    cmd = cmd.strip()
    result = CommandResult(cwd=get_current_dir())

    if not cmd:
        return result

    # cd handling — updates the shared per-thread cwd, no subprocess.
    if cmd.startswith("cd"):
        ok, msg = handle_cd(cmd)
        rest = cmd[2:].strip()
        chained = None
        for sep in (";", "&&"):
            idx = rest.find(sep)
            if idx != -1:
                chained = rest[idx + len(sep):].strip()
                break
        if chained and ok:
            result.message = f"cd: {msg}"
            cmd = chained
        else:
            result.message = msg
            result.cwd = get_current_dir()
            if not ok:
                result.exit_code = 1
                result.stderr = msg + "\n"
            return result

    # File safety: snapshot files the command may overwrite (redirects,
    # sed -i, tee, cp/mv, truncate, dd of=...).
    result.snapshots = snapshot_targets_from_command(cmd)

    processed = preprocess(cmd)
    cap = max_output if max_output is not None else MAX_OUTPUT_BYTES
    process = None
    killed = threading.Event()
    watchdog = None
    stdout_lines: List[str] = []
    stderr_lines: List[str] = []
    sent_bytes = 0
    truncated = False
    timed_out = False

    def _reader(pipe, sink: List[str], is_stderr: bool) -> None:
        nonlocal sent_bytes, truncated
        for line in pipe:
            if killed.is_set():
                break
            sent_bytes += len(line.encode())
            if sent_bytes <= cap:
                sink.append(line)
                if stream:
                    try:
                        stream(line, is_stderr)
                    except Exception:
                        pass
            elif not truncated:
                truncated = True
                if stream:
                    try:
                        stream(TRUNCATION_MARKER, is_stderr)
                    except Exception:
                        pass

    try:
        popen_kwargs = {
            "shell": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.PIPE,
            "text": True,
            "cwd": get_current_dir(),
        }
        if hasattr(os, "setsid"):
            popen_kwargs["preexec_fn"] = os.setsid

        process = subprocess.Popen(f"{shell_prefix()}{processed}", **popen_kwargs)
        set_active_pid(process.pid)
        _spawn_auto_input(process, cmd)

        # Timeout watchdog — only armed when a positive timeout is set.
        # Default 0 = commands run until they finish (pkg upgrade etc.).
        effective_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        if effective_timeout > 0:
            def _timeout_watchdog() -> None:
                try:
                    process.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    killed.set()
                    try:
                        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            time.sleep(1)
                        process.kill()
                    except Exception:
                        process.kill()

            watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
            watchdog.start()

        t1 = threading.Thread(
            target=_reader, args=(process.stdout, stdout_lines, False), daemon=True
        )
        t2 = threading.Thread(
            target=_reader, args=(process.stderr, stderr_lines, True), daemon=True
        )
        t1.start()
        t2.start()

        process.wait()
        t1.join(timeout=5)
        t2.join(timeout=5)
        if watchdog is not None:
            watchdog.join(timeout=2)
    except Exception as e:
        result.stderr += f"Error: {e}\n"
        result.exit_code = 1
    finally:
        set_active_pid(None)
        result.stdout = "".join(stdout_lines)
        result.stderr = "".join(stderr_lines)
        result.exit_code = process.returncode if process is not None else 1
        result.truncated = truncated
        result.timed_out = killed.is_set()
        result.cancelled = killed.is_set()
        result.cwd = get_current_dir()
    return result


# ── Filesystem operations ────────────────────────────────────────────────────

def read_file(
    path: str,
    offset: int = 0,
    limit: int = 500,
    workspace: Optional[str] = None,
) -> dict:
    """Read a text file with line offset/limit support."""
    resolved = resolve_path(path, workspace)
    if resolved is None:
        return {"error": "Path not allowed"}
    if not os.path.isfile(resolved):
        return {"error": f"Not a file: {resolved}"}
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": str(e)}
    total = len(lines)
    start = max(0, int(offset or 0))
    end = min(total, start + max(1, int(limit or 1)))
    return {
        "path": resolved,
        "content": "".join(lines[start:end]),
        "offset": start,
        "limit": end - start,
        "total_lines": total,
        "truncated": end < total,
    }


def write_file(
    path: str,
    content: str,
    workspace: Optional[str] = None,
) -> dict:
    """Write text content to a file. The previous version is snapshotted."""
    resolved = resolve_path(path, workspace)
    if resolved is None:
        return {"error": "Path not allowed"}
    snap = snapshot_before_write(resolved)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return {"error": str(e)}
    return {"path": resolved, "written": True, "snapshot": snap}


def list_files(
    path: str = ".",
    workspace: Optional[str] = None,
) -> dict:
    """List directory entries (including dotfiles)."""
    resolved = resolve_path(path, workspace)
    if resolved is None:
        return {"error": "Path not allowed"}
    if not os.path.isdir(resolved):
        return {"error": f"Not a directory: {resolved}"}
    try:
        entries = sorted(os.listdir(resolved))
    except OSError as e:
        return {"error": str(e)}
    return {"path": resolved, "entries": entries, "count": len(entries)}


def make_directory(
    path: str,
    workspace: Optional[str] = None,
) -> dict:
    """Create a directory (and any missing parents)."""
    resolved = resolve_path(path, workspace)
    if resolved is None:
        return {"error": "Path not allowed"}
    try:
        os.makedirs(resolved, exist_ok=True)
    except OSError as e:
        return {"error": str(e)}
    return {"path": resolved, "created": True}


# ── Device operations ────────────────────────────────────────────────────────

def _run_device_command(cmd: str) -> dict:
    """Run a termux-* command and return {raw, data, error}."""
    result = execute_command(cmd)
    raw = result.stdout.strip() or "{}"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        data = {"raw": raw}
    return {"raw": raw, "data": data, "error": result.stderr or None}


def get_battery() -> dict:
    """Get battery status as a structured result."""
    return _run_device_command("termux-battery-status 2>/dev/null || echo '{}'")


def get_location(provider: str = "gps") -> dict:
    """Get the device's last known location."""
    provider = (provider or "gps").strip()
    return _run_device_command(
        f"termux-location -p {shell_quote(provider)} -r last 2>/dev/null || echo '{{}}'"
    )


def send_notification(
    title: str = "TermuxGPT",
    content: str = "",
    priority: str = "default",
    nid: str = "",
    ongoing: bool = False,
) -> dict:
    """Send a device notification."""
    if not content:
        return {"error": "Missing 'content'"}
    flags = ""
    if nid:
        flags += f" --id {shell_quote(nid)}"
    if ongoing:
        flags += " --ongoing"
    result = execute_command(
        f"termux-notification {flags} --priority {shell_quote(priority)} "
        f"--title {shell_quote(title)} --content {shell_quote(content)} "
        f"2>/dev/null && echo 'Notification sent' || echo 'Notification failed'"
    )
    return {
        "sent": "Notification sent" in result.stdout,
        "output": result.stdout.strip(),
        "error": result.stderr or None,
    }