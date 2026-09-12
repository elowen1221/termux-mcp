"""Tests for FastMCP transport security (DNS rebinding protection).

Covers: localhost Host always allowed, the current trusted tunnel Host
allowed, arbitrary Hosts rejected, tunnel hostname changes replacing (not
accumulating) trust, and the runtime public-URL watcher lifecycle. OAuth
discovery / 401 challenge / tunnel behavior is covered by the existing
suites and must not regress.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from termux_mcp import config
from termux_mcp.config import AUTH_TOKEN
from termux_mcp.mcp_server import (
    _LOCALHOST_HOSTS,
    _apply_public_url,
    _build_mcp_app,
    _host_entries_for_url,
)


@pytest.fixture
def isolated_public_url(monkeypatch, tmp_path):
    """Isolate the runtime public-URL registry from any real state."""
    monkeypatch.setattr(config, "PUBLIC_URL_FILE", str(tmp_path / "public_url"))
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    yield


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server(app):
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=0.3)
            break
        except Exception:
            time.sleep(0.1)
    return server, thread, port


def _stop_server(server, thread):
    server.should_exit = True
    thread.join(timeout=5)


def _raw_status(port, host, path="/mcp", token=None):
    """Send a raw HTTP GET with a custom Host header; return the status code.

    The transport-security middleware answers 421 for a disallowed Host and
    lets the request through otherwise (GET /mcp then answers 406 without an
    Accept header), so 421 is the unambiguous "Host rejected" signal.
    """
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Connection: close"]
    if token:
        lines.append(f"Authorization: Bearer {token}")
    s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    data = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    s.close()
    return int(data.split(b"\r\n", 1)[0].split(b" ", 2)[1])


# ── Unit: allowed_hosts derivation / replacement ─────────────────────────────

def test_host_entries_for_url():
    assert _host_entries_for_url("https://ejnuj-81-28-13-138.free.pinggy.net") == [
        "ejnuj-81-28-13-138.free.pinggy.net",
        "ejnuj-81-28-13-138.free.pinggy.net:*",
    ]
    assert _host_entries_for_url("https://example.com:8443/mcp") == [
        "example.com",
        "example.com:*",
    ]
    assert _host_entries_for_url("not a url") == []
    assert _host_entries_for_url("") == []


def test_apply_public_url_preserves_localhost_and_replaces_old_host():
    from mcp.server.transport_security import TransportSecuritySettings

    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(_LOCALHOST_HOSTS),
    )
    _apply_public_url(settings, "https://tunnel-a.example.com")
    assert settings.allowed_hosts == _LOCALHOST_HOSTS + [
        "tunnel-a.example.com",
        "tunnel-a.example.com:*",
    ]
    # hostname change: new host trusted, old host removed (no accumulation)
    _apply_public_url(settings, "https://tunnel-b.example.com")
    assert settings.allowed_hosts == _LOCALHOST_HOSTS + [
        "tunnel-b.example.com",
        "tunnel-b.example.com:*",
    ]
    assert "tunnel-a.example.com" not in settings.allowed_hosts
    # cleared: back to localhost-only
    _apply_public_url(settings, "")
    assert settings.allowed_hosts == _LOCALHOST_HOSTS


# ── Integration: Host header validation on /mcp ──────────────────────────────

def test_localhost_host_allowed(isolated_public_url):
    app = _build_mcp_app()
    server, thread, port = _start_server(app)
    try:
        assert _raw_status(port, f"127.0.0.1:{port}", token=AUTH_TOKEN) != 421
        assert _raw_status(port, f"localhost:{port}", token=AUTH_TOKEN) != 421
    finally:
        _stop_server(server, thread)


def test_trusted_tunnel_host_allowed_and_malicious_rejected(isolated_public_url):
    from termux_mcp import mcp_server

    app = _build_mcp_app()
    _apply_public_url(mcp_server._transport_security, "https://tunnel.example.com")
    server, thread, port = _start_server(app)
    try:
        # trusted tunnel Host passes DNS rebinding protection
        assert _raw_status(port, "tunnel.example.com", token=AUTH_TOKEN) != 421
        # arbitrary Host rejected
        assert _raw_status(port, "evil.example.com", token=AUTH_TOKEN) == 421
        # localhost still allowed alongside the tunnel host
        assert _raw_status(port, f"127.0.0.1:{port}", token=AUTH_TOKEN) != 421
    finally:
        _stop_server(server, thread)


def test_tunnel_hostname_change_replaces_trust(isolated_public_url):
    from termux_mcp import mcp_server

    app = _build_mcp_app()
    _apply_public_url(mcp_server._transport_security, "https://tunnel-a.example.com")
    server, thread, port = _start_server(app)
    try:
        assert _raw_status(port, "tunnel-a.example.com", token=AUTH_TOKEN) != 421
        assert _raw_status(port, "tunnel-b.example.com", token=AUTH_TOKEN) == 421
        # tunnel URL changes (new tunnel on restart)
        _apply_public_url(mcp_server._transport_security, "https://tunnel-b.example.com")
        assert _raw_status(port, "tunnel-b.example.com", token=AUTH_TOKEN) != 421
        # old host is no longer trusted
        assert _raw_status(port, "tunnel-a.example.com", token=AUTH_TOKEN) == 421
    finally:
        _stop_server(server, thread)


# ── Lifecycle: watcher picks up the runtime URL written by the CLI ───────────

def test_watcher_picks_up_runtime_url(isolated_public_url, monkeypatch):
    from termux_mcp import mcp_server

    monkeypatch.setattr(mcp_server, "_PUBLIC_URL_POLL_INTERVAL", 0.1)
    app = _build_mcp_app()
    settings = mcp_server._transport_security
    assert settings.allowed_hosts == _LOCALHOST_HOSTS

    # Simulate the CLI writing the runtime URL after a tunnel succeeds.
    config.set_public_url("https://tunnel.example.com")
    thread = threading.Thread(
        target=mcp_server._watch_public_url, args=(settings,), daemon=True
    )
    thread.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            if "tunnel.example.com" in settings.allowed_hosts:
                break
            time.sleep(0.05)
        assert "tunnel.example.com" in settings.allowed_hosts
        assert "tunnel.example.com:*" in settings.allowed_hosts
        assert _LOCALHOST_HOSTS[0] in settings.allowed_hosts
    finally:
        config.clear_public_url()


# ── Lifecycle: server-only restart restores the persisted public URL ─────────

def test_restart_restores_public_url_allowed_host_and_issuer(
    isolated_public_url, monkeypatch
):
    """After a server-only restart the persisted public URL is re-read:
    the tunnel host is trusted again and OAuth discovery resolves to it."""
    from termux_mcp import mcp_server, oauth

    monkeypatch.setattr(config, "OAUTH_ISSUER", "auto")
    # Simulate the CLI keeping a verified tunnel URL across a restart.
    config.set_public_url("https://abc123.free.pinggy.net")
    try:
        app = _build_mcp_app()  # fresh server process reads the persisted URL
        settings = mcp_server._transport_security
        assert "abc123.free.pinggy.net" in settings.allowed_hosts
        assert "abc123.free.pinggy.net:*" in settings.allowed_hosts
        assert _LOCALHOST_HOSTS[0] in settings.allowed_hosts
        # OAuth discovery resolves to the restored runtime URL.
        assert oauth.get_issuer() == "https://abc123.free.pinggy.net"
        assert oauth.get_resource_url() == "https://abc123.free.pinggy.net/mcp"
    finally:
        config.clear_public_url()