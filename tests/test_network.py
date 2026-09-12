import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from termux_mcp import network, process


class _InitHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def test_mcp_initialize_probe_direct_loopback():
    server = HTTPServer(("127.0.0.1", 0), _InitHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ok, detail = process.mcp_initialize_probe(server.server_port, "token", timeout=1.0)
        assert ok is True
        assert "2025-03-26" in detail
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_kill_port_has_hard_deadline(monkeypatch):
    # Simulate Android/lsof failing to identify a listener while TCP continues
    # to accept connections. Startup must fail in bounded time, never loop forever.
    monkeypatch.setattr(network, "_pids_on_port", lambda port: [])

    class AlwaysOpenSocket:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def settimeout(self, timeout):
            pass
        def connect_ex(self, addr):
            return 0

    monkeypatch.setattr(socket, "socket", lambda *a, **k: AlwaysOpenSocket())
    clock = {"t": 0.0}
    monkeypatch.setattr(network.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(network.time, "sleep", lambda delay: clock.__setitem__("t", clock["t"] + max(delay, 0.1)))

    with pytest.raises(TimeoutError, match="refusing to wait forever"):
        network.kill_port(8080, timeout=0.3)


def test_kill_port_returns_when_closed(monkeypatch):
    monkeypatch.setattr(network, "_pids_on_port", lambda port: [])

    class ClosedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def settimeout(self, timeout):
            pass
        def connect_ex(self, addr):
            return 111

    monkeypatch.setattr(socket, "socket", lambda *a, **k: ClosedSocket())
    network.kill_port(8080, timeout=0.3)
