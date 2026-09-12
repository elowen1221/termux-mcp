import os
import socket
import subprocess
import time

from .config import PORT_POLL_INTERVAL


def _pids_on_port(port: int) -> list[int]:
    """Return numeric PIDs listening on a TCP port without invoking a shell."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    result = subprocess.run(
        ["lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
        timeout=2.0,
    )
    pids = []
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if raw.isdigit():
            pids.append(int(raw))
    return pids


def kill_port(port: int, timeout: float = 5.0) -> None:
    """Best-effort cleanup of a stale listener, with a hard deadline.

    Port cleanup is a startup fallback, not a supervisor.  In particular, it
    must never block server startup forever when Android/lsof cannot identify
    the process that owns a socket.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    try:
        pids = _pids_on_port(port)
    except (OSError, ValueError, subprocess.SubprocessError):
        pids = []

    for pid in pids:
        try:
            os.kill(pid, 15)
        except (ProcessLookupError, PermissionError):
            pass

    deadline = time.monotonic() + timeout
    forced = False
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(min(0.5, max(0.05, deadline - time.monotonic())))
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        # If a listener we identified ignored SIGTERM, force it once near the
        # middle of the grace period.  Unknown listeners are never killed by
        # guesswork.
        if pids and not forced and time.monotonic() >= deadline - timeout / 2:
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except (ProcessLookupError, PermissionError):
                    pass
            forced = True
        time.sleep(PORT_POLL_INTERVAL)

    raise TimeoutError(
        f"port {port} is still accepting connections after {timeout:.1f}s; "
        "refusing to wait forever"
    )
