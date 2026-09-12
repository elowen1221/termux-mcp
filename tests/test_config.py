"""Tests for persistent config and token management.

Covers: token auto-generation + persistence, chmod 600, rotation,
token_configured, and that the token never appears in launcher output.
"""

import os
import stat

import pytest

from termux_mcp import config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point config at a temp dir with no token set."""
    saved_values = dict(config._FILE_VALUES)
    saved_token = config.AUTH_TOKEN
    saved_required = config.REQUIRE_AUTH
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "cfg" / "config.env"))
    monkeypatch.setattr(config, "AUTH_TOKEN", "")
    monkeypatch.setattr(config, "REQUIRE_AUTH", False)
    monkeypatch.setattr(config, "CLIENT_TARGET", "chatgpt")
    monkeypatch.setattr(config, "PERMISSION_MODE", "standard")
    monkeypatch.setattr(config, "SETUP_COMPLETE", False)
    monkeypatch.setattr(config, "OAUTH_ISSUER", "")
    yield config
    config._FILE_VALUES.clear()
    config._FILE_VALUES.update(saved_values)
    config.AUTH_TOKEN = saved_token
    config.REQUIRE_AUTH = saved_required


def test_ensure_token_generates_and_persists(isolated_config):
    token = config.ensure_token()
    assert len(token) >= 32
    assert config.token_configured() is True
    assert os.path.exists(config.CONFIG_FILE)
    with open(config.CONFIG_FILE, encoding="utf-8") as f:
        content = f.read()
    assert token in content
    assert "TERMUX_MCP_AUTH_TOKEN=" in content


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_config_file_permission_600(isolated_config):
    config.ensure_token()
    mode = stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode)
    assert mode == 0o600


def test_ensure_token_idempotent(isolated_config):
    first = config.ensure_token()
    second = config.ensure_token()
    assert first == second


def test_rotate_token_changes(isolated_config):
    old = config.ensure_token()
    new = config.rotate_token()
    assert new != old
    assert config.AUTH_TOKEN == new
    with open(config.CONFIG_FILE, encoding="utf-8") as f:
        assert new in f.read()


def test_token_configured_false_when_unset(isolated_config):
    assert config.token_configured() is False


def test_token_not_in_launcher_output(isolated_config, monkeypatch, capsys):
    """`termux-mcp start` prints the token length, never the token itself."""
    from termux_mcp import cli, process

    class Args:
        tunnel = "none"
        no_tunnel = True

    monkeypatch.setattr(cli, "ensure_token", lambda: "super-secret-token-0123456789abcdef")
    monkeypatch.setattr(process, "is_running", lambda: False)
    monkeypatch.setattr(process, "start_server", lambda env=None: 12345)
    monkeypatch.setattr(process, "wait_http", lambda port, timeout=15: True)

    cli.cmd_start(Args())
    out = capsys.readouterr().out
    assert "super-secret-token-0123456789abcdef" not in out
    assert "configured" in out


def test_token_command_hides_by_default(isolated_config, monkeypatch, capsys):
    from termux_mcp import cli

    class Args:
        show = False
        rotate = False

    monkeypatch.setattr(config, "AUTH_TOKEN", "hidden-token-0123456789")
    cli.cmd_token(Args())
    out = capsys.readouterr().out
    assert "hidden-token-0123456789" not in out
    assert "configured" in out


def test_save_user_preferences_persists_onboarding(isolated_config):
    config.save_user_preferences("claude", "full")
    assert config.CLIENT_TARGET == "claude"
    assert config.PERMISSION_MODE == "full"
    assert config.SETUP_COMPLETE is True
    assert config.OAUTH_ISSUER == "auto"
    with open(config.CONFIG_FILE, encoding="utf-8") as f:
        content = f.read()
    assert "TERMUX_MCP_CLIENT=claude" in content
    assert "TERMUX_MCP_PERMISSIONS=full" in content
    assert "TERMUX_MCP_SETUP_COMPLETE=1" in content
    assert "TERMUX_MCP_OAUTH_ISSUER=auto" in content
