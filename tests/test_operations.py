"""Tests for the shared operations layer (termux_mcp.operations).

These cover the security invariants that both the REST API and the MCP
layer rely on: risk gating, snapshot-before-write, workspace boundaries
(path traversal / symlink escape), and offset/limit file reads.
"""

import os

import pytest

from termux_mcp import operations
from termux_mcp.handler import MCPHandler


# ── Risk gating ──────────────────────────────────────────────────────────────

def test_dangerous_command_blocked():
    a = operations.assess_command("rm -rf /")
    assert a["blocked"] is True
    assert a["risk_level"] == "dangerous"


def test_dangerous_command_blocked_rm_root_glob():
    a = operations.assess_command("rm -rf /*")
    assert a["blocked"] is True


def test_warning_command_requires_confirmation():
    a = operations.assess_command("rm -rf somefile")
    assert a["blocked"] is False
    assert a["confirmation_required"] is True
    assert a["risk_level"] == "warning"


def test_warning_command_confirmed_passes():
    a = operations.assess_command("rm -rf somefile", confirmed=True)
    assert a["blocked"] is False
    assert a["confirmation_required"] is False


def test_safe_command_passes():
    a = operations.assess_command("echo hello")
    assert a["blocked"] is False
    assert a["confirmation_required"] is False
    assert a["risk_level"] == "safe"


# ── Command execution ────────────────────────────────────────────────────────

def test_execute_command_structured_result():
    r = operations.execute_command("echo hello")
    assert r.exit_code == 0
    assert "hello" in r.stdout
    assert r.risk_level == "safe"
    assert r.truncated is False
    assert isinstance(r.snapshots, list)


def test_execute_command_stderr_and_exit_code():
    # Cross-platform: `>&2` / `exit` are sh syntax, invalid on Windows cmd.
    r = operations.execute_command(
        'python -c "import sys; print(\'boom\', file=sys.stderr); sys.exit(3)"'
    )
    assert r.exit_code == 3
    assert "boom" in r.stderr


def test_execute_command_stream_callback():
    lines = []
    r = operations.execute_command("echo a; echo b", stream=lambda line, is_stderr: lines.append(line))
    assert r.exit_code == 0
    assert any("a" in l for l in lines)
    assert any("b" in l for l in lines)


# ── File reads with offset/limit ─────────────────────────────────────────────

def test_read_file_offset_limit(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("".join(f"line{i}\n" for i in range(10)))
    res = operations.read_file(str(p), offset=2, limit=3)
    assert res["content"] == "line2\nline3\nline4\n"
    assert res["offset"] == 2
    assert res["limit"] == 3
    assert res["total_lines"] == 10
    assert res["truncated"] is True


def test_read_file_no_truncation_when_short(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("one\ntwo\n")
    res = operations.read_file(str(p))
    assert res["content"] == "one\ntwo\n"
    assert res["truncated"] is False


# ── Snapshot-before-write ────────────────────────────────────────────────────

def test_write_file_snapshots_previous_version(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("old")
    res = operations.write_file(str(p), "new")
    assert res["written"] is True
    assert res["snapshot"] is not None
    assert os.path.exists(res["snapshot"])
    assert p.read_text() == "new"
    with open(res["snapshot"], encoding="utf-8") as f:
        assert f.read() == "old"


def test_write_file_new_file_no_snapshot(tmp_path):
    p = tmp_path / "new.txt"
    res = operations.write_file(str(p), "fresh")
    assert res["written"] is True
    assert res["snapshot"] is None


# ── Workspace boundary (path traversal / symlink escape) ────────────────────

def test_workspace_traversal_blocked(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    # Absolute path outside the workspace.
    res = operations.read_file(str(outside), workspace=str(ws))
    assert "error" in res
    # Relative traversal from inside the workspace.
    res2 = operations.read_file("../secret.txt", workspace=str(ws))
    assert "error" in res2


def test_workspace_allows_inside_paths(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = ws / "ok.txt"
    inside.write_text("ok")
    res = operations.read_file(str(inside), workspace=str(ws))
    assert "error" not in res
    assert res["content"] == "ok"


def test_symlink_escape_blocked_all_fs_tools(tmp_path):
    """POSIX: a symlink inside the workspace pointing outside must not let
    any filesystem tool escape the workspace boundary.

    resolve_path() resolves with realpath, so the symlink's *textual* path
    (which lies inside the workspace) is rejected because its real target
    resolves outside the workspace. Runs normally on POSIX; skipped on
    Windows when symlink creation is unavailable.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret")
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()

    link_file = ws / "link.txt"
    link_dir = ws / "link_dir"
    try:
        os.symlink(outside_file, link_file)
        os.symlink(outside_dir, link_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    # The textual path is inside the workspace...
    assert str(link_file).startswith(str(ws))
    # ...but its realpath escapes it — resolve_path must reject on realpath,
    # not merely on the textual path.
    assert os.path.realpath(link_file) == str(outside_file)
    assert os.path.realpath(link_dir) == str(outside_dir)
    assert operations.resolve_path(str(link_file), workspace=str(ws)) is None
    assert operations.resolve_path(str(link_dir), workspace=str(ws)) is None

    # read_file cannot read through the symlink.
    res = operations.read_file(str(link_file), workspace=str(ws))
    assert "error" in res

    # write_file cannot write through the symlink; the outside file is untouched.
    res = operations.write_file(str(link_file), "pwned", workspace=str(ws))
    assert "error" in res
    assert outside_file.read_text() == "secret"

    # list_files cannot list through the symlinked directory.
    res = operations.list_files(str(link_dir), workspace=str(ws))
    assert "error" in res

    # make_directory cannot create through the symlinked directory.
    res = operations.make_directory(str(link_dir / "sub"), workspace=str(ws))
    assert "error" in res
    assert not (outside_dir / "sub").exists()


def test_workspace_boundary_applies_to_all_fs_tools(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert "error" in operations.list_files(str(outside), workspace=str(ws))
    assert "error" in operations.make_directory(str(outside / "x"), workspace=str(ws))
    assert "error" in operations.write_file(str(outside / "x.txt"), "x", workspace=str(ws))


# ── REST and MCP share the same underlying operations ────────────────────────

class _FakeWfile:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data
        return len(data)

    def flush(self):
        pass


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler used by _handle_run."""

    def __init__(self):
        self.wfile = _FakeWfile()
        self.status = None
        self.headers = {}

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    def _stream_chunk(self, line, is_stderr=False):
        from termux_mcp.shell import _send_chunk
        _send_chunk(self, line)

    def _send_text(self, text, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(text.encode())))
        self.end_headers()
        self.wfile.write(text.encode())


def test_rest_and_mcp_share_execute_command(monkeypatch):
    calls = []

    def fake_execute(cmd, timeout=None, max_output=None, stream=None):
        calls.append(cmd)
        return operations.CommandResult(stdout="ok\n", exit_code=0)

    monkeypatch.setattr(operations, "execute_command", fake_execute)

    # MCP path.
    from termux_mcp import mcp_server
    mcp_server.tool_run_command("echo mcp")

    # REST path.
    fake = _FakeHandler()
    MCPHandler._handle_run(fake, {"cmd": "echo rest"})

    assert calls == ["echo mcp", "echo rest"]


def test_rest_and_mcp_share_assess_command(monkeypatch):
    calls = []

    def fake_assess(cmd, confirmed=False):
        calls.append((cmd, confirmed))
        return {"blocked": False, "confirmation_required": False,
                "risk_level": "safe", "message": ""}

    monkeypatch.setattr(operations, "assess_command", fake_assess)

    from termux_mcp import mcp_server
    mcp_server.tool_run_command("echo mcp")

    fake = _FakeHandler()
    MCPHandler._handle_run(fake, {"cmd": "echo rest"})

    assert calls == [("echo mcp", False), ("echo rest", False)]


def test_rest_and_mcp_share_read_file(monkeypatch):
    calls = []

    def fake_read(path, offset=0, limit=500, workspace=None):
        calls.append((path, offset, limit, workspace))
        return {"content": "x", "path": path}

    monkeypatch.setattr(operations, "read_file", fake_read)

    from termux_mcp import mcp_server
    mcp_server.tool_read_file("/tmp/a", offset=1, limit=2)

    fake = _FakeHandler()
    MCPHandler._handle_read(fake, {"path": "/tmp/b", "offset": 3, "limit": 4})

    # MCP passes WORKSPACE_ROOT ("" when unset); REST passes the default None.
    assert calls == [("/tmp/a", 1, 2, ""), ("/tmp/b", 3, 4, None)]