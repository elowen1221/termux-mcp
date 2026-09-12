"""Tests for the CLI launcher: process management, duplicate prevention,
stop/status, Python version detection, and dependency compatibility.
"""

import json
import os
import sys

import pytest

from termux_mcp import cli, process


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Point process state files at a temp dir."""
    monkeypatch.setattr(process, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(process, "PID_FILE", str(tmp_path / "server.pid"))
    monkeypatch.setattr(process, "TUNNEL_PID_FILE", str(tmp_path / "tunnel.pid"))
    monkeypatch.setattr(process, "LOG_FILE", str(tmp_path / "server.log"))
    monkeypatch.setattr(process, "TUNNEL_LOG_FILE", str(tmp_path / "tunnel.log"))
    return tmp_path


# ── Python version detection ─────────────────────────────────────────────────

def test_python_version_detection():
    assert sys.version_info >= (3, 10)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.27.9", False),
        ("1.28.0", True),
        ("1.99.0", True),
        ("2.0.0", False),
        ("not-a-version", False),
        (None, False),
    ],
)
def test_version_range(value, expected):
    assert cli._version_in_range(value, "1.28", "2") is expected


def test_pkg_version_found():
    assert cli._pkg_version("mcp") is not None


def test_pkg_version_missing():
    assert cli._pkg_version("definitely-not-a-package-xyz-123") is None


# ── Duplicate process prevention ─────────────────────────────────────────────

def test_duplicate_process_prevention(isolated_state):
    # Simulate a running server by writing our own PID.
    process.write_pid(os.getpid())
    assert process.is_running() is True
    with pytest.raises(RuntimeError):
        process.start_server()
    process.clear_pid()
    assert process.is_running() is False


def test_start_server_writes_pid(isolated_state):
    # start_server spawns a real child; verify PID file + running state.
    pid = process.start_server()
    try:
        assert process.read_pid() == pid
        # Wait for the child to actually start executing (writes to the log).
        # On Windows under load, process creation can lag; stopping a child
        # that is still in loader initialization is racy.
        import time
        deadline = time.time() + 20
        while time.time() < deadline:
            if process.tail_log(1):
                break
            time.sleep(0.2)
        assert process.is_running() is True
    finally:
        process.stop_server(timeout=10)
    assert process.is_running() is False


# ── stop / status ────────────────────────────────────────────────────────────

def test_stop_when_not_running(isolated_state):
    assert process.is_running() is False
    assert process.stop_server() is False


def test_stop_clears_stale_pid(isolated_state):
    process.write_pid(99999999)  # almost certainly dead
    assert process.is_running() is False
    process.stop_server()
    assert process.read_pid() is None


def test_tunnel_pid_roundtrip(isolated_state):
    process.write_tunnel_pid(12345)
    assert process.read_tunnel_pid() == 12345
    process.clear_tunnel_pid()
    assert process.read_tunnel_pid() is None


def test_tunnel_is_running_live_pid(isolated_state):
    process.write_tunnel_pid(os.getpid())
    assert process.tunnel_is_running() is True
    assert process.read_tunnel_pid() == os.getpid()


def test_tunnel_is_running_stale_pid_cleaned(isolated_state):
    """A dead tunnel PID must report not-running AND clean the stale file."""
    process.write_tunnel_pid(99999999)  # almost certainly dead
    assert process.tunnel_is_running() is False
    assert process.read_tunnel_pid() is None  # stale pidfile removed


def test_tail_tunnel_log(isolated_state):
    (isolated_state / "tunnel.log").write_text(
        "line1\nline2\nline3\n", encoding="utf-8"
    )
    assert process.tail_tunnel_log(2) == "line2\nline3\n"
    assert process.tail_tunnel_log(50) == "line1\nline2\nline3\n"


def test_status_uses_tunnel_is_running(isolated_state, monkeypatch, capsys):
    """status must only report a tunnel when its PID is really alive."""
    monkeypatch.setattr(process, "is_running", lambda: False)
    monkeypatch.setattr(process, "port_open", lambda port, **kw: False)
    monkeypatch.setattr(process, "tunnel_is_running", lambda: True)
    monkeypatch.setattr(process, "read_tunnel_pid", lambda: 12345)
    rc = cli.cmd_status()
    out = capsys.readouterr().out
    assert "Tunnel: running (pid 12345)" in out
    assert rc == 1  # server not running


def test_port_open_closed(isolated_state):
    # A port we are not listening on.
    assert process.port_open(1, timeout=0.2) is False


# ── CLI command wiring ───────────────────────────────────────────────────────

def test_parse_args_default_runs_server():
    args = cli._parse_args([])
    assert args.command is None


def test_parse_args_start_tunnel_choices():
    for choice in ("auto", "pinggy", "cloudflare", "localhost-run", "none"):
        args = cli._parse_args(["start", "--tunnel", choice])
        assert args.command == "start"
        assert args.tunnel == choice


def test_parse_args_no_tunnel():
    args = cli._parse_args(["start", "--no-tunnel"])
    assert args.no_tunnel is True


def test_parse_args_token_rotate():
    args = cli._parse_args(["token", "--rotate"])
    assert args.command == "token"
    assert args.rotate is True


def test_parse_args_doctor_json():
    args = cli._parse_args(["doctor", "--json"])
    assert args.command == "doctor"
    assert args.json_output is True


def test_parse_args_setup_and_permissions():
    setup = cli._parse_args([
        "setup", "--client", "grok", "--permissions", "full", "--non-interactive"
    ])
    assert setup.command == "setup"
    assert setup.client == "grok"
    assert setup.permissions == "full"
    permissions = cli._parse_args(["permissions", "set", "read-only"])
    assert permissions.permissions_action == "set"
    assert permissions.mode == "read-only"


def test_doctor_runs_without_crashing(capsys):
    rc = cli.cmd_doctor()
    out = capsys.readouterr().out
    assert "PASS" in out or "WARN" in out or "FAIL" in out
    assert rc in (0, 1)


def test_doctor_json_is_machine_readable(capsys):
    rc = cli.cmd_doctor(json_output=True)
    report = json.loads(capsys.readouterr().out)
    assert rc in (0, 1)
    assert report["version"]
    assert set(report["summary"]) == {"pass", "warn", "fail"}
    assert report["checks"]
    assert all(
        set(check) == {"id", "name", "status", "detail"}
        for check in report["checks"]
    )
    assert len({check["id"] for check in report["checks"]}) == len(report["checks"])


# ── restart semantics (server/tunnel lifecycle decoupling) ───────────────────

def test_restart_tunnel_action_default_is_keep():
    args = cli._parse_args(["restart"])
    assert cli._restart_tunnel_action(args) == "keep"


def test_restart_tunnel_action_explicit_rebuild():
    for choice in ("auto", "pinggy", "cloudflare", "localhost-run", "none"):
        args = cli._parse_args(["restart", "--tunnel", choice])
        assert cli._restart_tunnel_action(args) == "rebuild"


def test_restart_tunnel_action_no_tunnel_stops():
    args = cli._parse_args(["restart", "--no-tunnel"])
    assert cli._restart_tunnel_action(args) == "stop"


@pytest.fixture
def restart_mocks(monkeypatch):
    """Mock process + cmd_start so restart semantics are testable without
    spawning real subprocesses or sleeping."""
    calls = {"killed": [], "started": [], "cleared_url": 0}
    monkeypatch.setattr(process, "is_running", lambda: True)
    monkeypatch.setattr(process, "read_pid", lambda: 1111)
    monkeypatch.setattr(process, "stop_server", lambda timeout=10.0: True)
    monkeypatch.setattr(process, "clear_pid", lambda: None)
    monkeypatch.setattr(process, "tunnel_is_running", lambda: True)
    monkeypatch.setattr(process, "read_tunnel_pid", lambda: 2222)
    monkeypatch.setattr(
        process, "kill_pid",
        lambda pid, timeout=5.0: calls["killed"].append(pid) or True,
    )
    monkeypatch.setattr(process, "clear_tunnel_pid", lambda: None)
    monkeypatch.setattr(
        cli, "clear_public_url",
        lambda: calls.__setitem__("cleared_url", calls["cleared_url"] + 1),
    )
    monkeypatch.setattr(
        cli, "cmd_start",
        lambda args: calls["started"].append(args) or 0,
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    return calls


def test_restart_default_keeps_tunnel_and_public_url(restart_mocks, capsys):
    rc = cli.cmd_restart(cli._parse_args(["restart"]))
    out = capsys.readouterr().out
    assert rc == 0
    # server-only: tunnel PID untouched, public URL not cleared
    assert restart_mocks["killed"] == []
    assert restart_mocks["cleared_url"] == 0
    assert "Tunnel kept (pid 2222)" in out
    # server restarted without touching the tunnel
    assert len(restart_mocks["started"]) == 1
    assert restart_mocks["started"][0].no_tunnel is True


def test_restart_rebuild_stops_tunnel_and_starts_new(restart_mocks, capsys):
    rc = cli.cmd_restart(cli._parse_args(["restart", "--tunnel", "auto"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert restart_mocks["killed"] == [2222]
    assert restart_mocks["cleared_url"] == 1
    assert "Tunnel stopped (pid 2222)" in out
    assert len(restart_mocks["started"]) == 1
    assert restart_mocks["started"][0].no_tunnel is False
    assert restart_mocks["started"][0].tunnel == "auto"


def test_restart_no_tunnel_stops_tunnel(restart_mocks, capsys):
    rc = cli.cmd_restart(cli._parse_args(["restart", "--no-tunnel"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert restart_mocks["killed"] == [2222]
    assert restart_mocks["cleared_url"] == 1
    assert len(restart_mocks["started"]) == 1
    assert restart_mocks["started"][0].no_tunnel is True


def test_restart_keep_clears_stale_public_url_when_tunnel_dead(monkeypatch, capsys):
    """keep mode with a dead tunnel must not leave a stale public URL."""
    calls = {"cleared_url": 0}
    monkeypatch.setattr(process, "is_running", lambda: False)
    monkeypatch.setattr(process, "clear_pid", lambda: None)
    monkeypatch.setattr(process, "tunnel_is_running", lambda: False)
    monkeypatch.setattr(process, "clear_tunnel_pid", lambda: None)
    monkeypatch.setattr(
        cli, "clear_public_url",
        lambda: calls.__setitem__("cleared_url", calls["cleared_url"] + 1),
    )
    monkeypatch.setattr(cli, "cmd_start", lambda args: 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    rc = cli.cmd_restart(cli._parse_args(["restart"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls["cleared_url"] == 1
    assert "No running tunnel to keep." in out


def test_restart_stale_server_pid_handled(monkeypatch, capsys):
    """A stale server PID must not crash restart; it just reports stopped."""
    calls = {"cleared_pid": 0}
    monkeypatch.setattr(process, "is_running", lambda: False)
    monkeypatch.setattr(
        process, "clear_pid",
        lambda: calls.__setitem__("cleared_pid", calls["cleared_pid"] + 1),
    )
    monkeypatch.setattr(process, "tunnel_is_running", lambda: True)
    monkeypatch.setattr(process, "read_tunnel_pid", lambda: 2222)
    monkeypatch.setattr(process, "kill_pid", lambda pid, timeout=5.0: True)
    monkeypatch.setattr(process, "clear_tunnel_pid", lambda: None)
    monkeypatch.setattr(cli, "cmd_start", lambda args: 0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    rc = cli.cmd_restart(cli._parse_args(["restart"]))
    out = capsys.readouterr().out
    assert rc == 0
    assert calls["cleared_pid"] == 1
    assert "Server is not running." in out


# ── profile isolation (TERMUX_MCP_PROFILE) ───────────────────────────────────

def _profile_probe(profile=None, extra_env=None):
    """Run a subprocess that prints config dirs/ports for a profile."""
    import json
    import subprocess
    import sys

    code = (
        "import json;"
        "from termux_mcp import config;"
        "print(json.dumps({"
        "'config_dir': config.CONFIG_DIR,"
        "'state_dir': config.STATE_DIR,"
        "'port': config.PORT,"
        "'mcp_port': config.MCP_PORT,"
        "'public_url_file': config.PUBLIC_URL_FILE,"
        "'config_file': config.CONFIG_FILE,"
        "}))"
    )
    env = os.environ.copy()
    env.pop("TERMUX_MCP_MCP_PORT", None)
    env.pop("TERMUX_MCP_PORT", None)
    env.pop("TERMUX_MCP_PROFILE", None)
    if profile is not None:
        env["TERMUX_MCP_PROFILE"] = profile
    if extra_env:
        env.update(extra_env)
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_profile_isolation_separate_dirs_and_ports():
    dev = _profile_probe("dev")
    assert dev["config_dir"].endswith("termux-mcp-dev")
    assert dev["state_dir"].endswith("termux-mcp-dev")
    assert dev["port"] == 18080
    assert dev["mcp_port"] == 18765
    assert os.path.dirname(dev["public_url_file"]).endswith("termux-mcp-dev")
    assert os.path.dirname(dev["config_file"]).endswith("termux-mcp-dev")


def test_profile_isolation_default_ports_without_profile():
    stable = _profile_probe(None)
    assert stable["config_dir"].endswith("termux-mcp")
    assert stable["state_dir"].endswith("termux-mcp")
    assert stable["port"] == 8080
    assert stable["mcp_port"] == 8765


def test_profile_isolation_explicit_env_still_wins():
    dev = _profile_probe("dev", extra_env={"TERMUX_MCP_PORT": "9999"})
    assert dev["port"] == 9999
    assert dev["mcp_port"] == 18765  # profile default for the MCP port


@pytest.mark.parametrize("profile", ["../escape", "bad/name", "a" * 33, "bad profile"])
def test_invalid_profile_is_rejected(profile):
    import subprocess

    env = os.environ.copy()
    env["TERMUX_MCP_PROFILE"] = profile
    result = subprocess.run(
        [sys.executable, "-c", "import termux_mcp.config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "Invalid TERMUX_MCP_PROFILE" in result.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TERMUX_MCP_PORT", "0"),
        ("TERMUX_MCP_MCP_PORT", "70000"),
        ("TERMUX_MCP_TIMEOUT", "forever"),
        ("TERMUX_MCP_MAX_OUTPUT", "12"),
        ("TERMUX_MCP_PERMISSIONS", "everything"),
    ],
)
def test_invalid_numeric_config_is_rejected(name, value):
    import subprocess

    env = os.environ.copy()
    env[name] = value
    result = subprocess.run(
        [sys.executable, "-c", "import termux_mcp.config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert f"Invalid {name}" in result.stderr
