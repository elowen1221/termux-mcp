"""Tests for the existing REST API.

Verifies the REST server still works after the shared-operations refactor:
/ping stays unauthenticated, every other endpoint requires a Bearer token,
and the /run risk gating (dangerous -> 403, warning -> confirmation) is
preserved.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from termux_mcp.config import AUTH_TOKEN
from termux_mcp.handler import MCPHandler
from termux_mcp.server import ThreadingHTTPServer


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _url(server, path):
    return f"http://127.0.0.1:{server.server_address[1]}{path}"


def _request(url, method="GET", body=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# ── Auth gates ───────────────────────────────────────────────────────────────

def test_ping_no_auth(server):
    status, body = _request(_url(server, "/ping"))
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_env_requires_auth(server):
    status, _ = _request(_url(server, "/env"))
    assert status == 401


def test_tools_requires_auth(server):
    status, _ = _request(_url(server, "/tools"))
    assert status == 401


def test_env_with_auth(server):
    status, body = _request(_url(server, "/env"), token=AUTH_TOKEN)
    assert status == 200
    assert "cwd" in json.loads(body)


def test_run_requires_auth(server):
    status, _ = _request(_url(server, "/run"), method="POST", body={"cmd": "echo hi"})
    assert status == 401


# ── /run behavior ────────────────────────────────────────────────────────────

def test_run_safe_command(server):
    status, body = _request(
        _url(server, "/run"), method="POST", body={"cmd": "echo hello"}, token=AUTH_TOKEN
    )
    assert status == 200
    assert "hello" in body


def test_run_dangerous_blocked(server):
    status, body = _request(
        _url(server, "/run"), method="POST", body={"cmd": "rm -rf /"}, token=AUTH_TOKEN
    )
    assert status == 403
    assert json.loads(body)["blocked"] is True


def test_run_warning_confirmation_required(server):
    status, body = _request(
        _url(server, "/run"), method="POST", body={"cmd": "rm -rf somefile"}, token=AUTH_TOKEN
    )
    assert status == 200
    parsed = json.loads(body)
    assert parsed["status"] == "confirmation_required"
    assert parsed["requires_confirmation"] is True


def test_run_warning_confirmed_executes(server):
    status, body = _request(
        _url(server, "/run"),
        method="POST",
        body={"cmd": "echo confirmed-ok", "confirmed": True},
        token=AUTH_TOKEN,
    )
    assert status == 200
    assert "confirmed-ok" in body


# ── File endpoints ───────────────────────────────────────────────────────────

def test_write_then_read(tmp_path, server):
    p = tmp_path / "a.txt"
    status, _ = _request(
        _url(server, "/write"),
        method="POST",
        body={"path": str(p), "content": "hello"},
        token=AUTH_TOKEN,
    )
    assert status == 200
    status, body = _request(
        _url(server, "/read"), method="POST", body={"path": str(p)}, token=AUTH_TOKEN
    )
    assert status == 200
    assert body == "hello"


def test_read_offset_limit(tmp_path, server):
    p = tmp_path / "b.txt"
    p.write_text("".join(f"line{i}\n" for i in range(10)))
    status, body = _request(
        _url(server, "/read"),
        method="POST",
        body={"path": str(p), "offset": 2, "limit": 2},
        token=AUTH_TOKEN,
    )
    assert status == 200
    assert body == "line2\nline3\n"


def test_mkdir(tmp_path, server):
    d = tmp_path / "newdir"
    status, _ = _request(
        _url(server, "/mkdir"), method="POST", body={"path": str(d)}, token=AUTH_TOKEN
    )
    assert status == 200
    assert d.is_dir()


def test_ls(tmp_path, server):
    (tmp_path / "x.txt").write_text("x")
    status, body = _request(
        _url(server, "/ls"), method="POST", body={"path": str(tmp_path)}, token=AUTH_TOKEN
    )
    assert status == 200
    assert "x.txt" in body