import os
import socket
import subprocess
import time

from .config import PORT_POLL_INTERVAL


def _pids_on_port(port: int) -> list[int]:
    """Return numeric PIDs listening/connected on a port without a shell."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    result = subprocess.run(
        ["lsof", "-t", f"-i:{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = []
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if raw.isdigit():
            pids.append(int(raw))
    return pids


def kill_port(port: int) -> None:
    try:
        for pid in _pids_on_port(port):
            try:
                os.kill(pid, 9)
            except (ProcessLookupError, PermissionError):
                pass
    except (OSError, ValueError):
        pass

    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(PORT_POLL_INTERVAL)
