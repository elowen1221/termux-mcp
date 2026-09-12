from termux_mcp import config, mcp_server, operations, permissions


def test_read_only_blocks_mutating_tools(monkeypatch):
    monkeypatch.setattr(config, "PERMISSION_MODE", "read-only")
    assert mcp_server.tool_write_file("/tmp/nope", "x")["error"] == "permission_denied"
    assert mcp_server.tool_make_directory("/tmp/nope")["error"] == "permission_denied"
    assert mcp_server.tool_run_command("echo nope")["error"] == "permission_denied"
    assert mcp_server.tool_mcp_remove("missing")["error"] == "permission_denied"


def test_standard_keeps_command_risk_gate(monkeypatch):
    monkeypatch.setattr(config, "PERMISSION_MODE", "standard")
    result = mcp_server.tool_run_command("rm -rf /")
    assert result["blocked"] is True


def test_full_mode_skips_command_gate_but_keeps_execution_layer(monkeypatch):
    monkeypatch.setattr(config, "PERMISSION_MODE", "full")
    monkeypatch.setattr(
        operations,
        "execute_command",
        lambda cmd: operations.CommandResult(stdout="trusted\n", exit_code=0),
    )
    result = mcp_server.tool_run_command("rm -rf /")
    assert result["exit_code"] == 0
    assert result["stdout"] == "trusted\n"
    assert result["risk_level"] == "dangerous"


def test_permission_status_is_owner_actionable(monkeypatch):
    monkeypatch.setattr(config, "PERMISSION_MODE", "full")
    result = permissions.status()
    assert result["mode"] == "full"
    assert result["full_control"] is True
    assert "termux-mcp permissions set" in result["change_command"]
