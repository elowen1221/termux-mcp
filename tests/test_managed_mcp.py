import json

import pytest

from termux_mcp import managed_mcp


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_mcp, "REGISTRY_FILE", tmp_path / "managed.json")
    monkeypatch.setattr(managed_mcp, "MANAGED_ROOT", tmp_path / "servers")
    return tmp_path


def test_register_remote_server_and_redact_auth(isolated_registry):
    result = managed_mcp.install(
        "https://mcp.example.com/mcp",
        name="example",
        authorization="secret-token",
    )
    assert result["transport"] == "http"
    assert result["authorization"] == "configured"
    listed = managed_mcp.list_servers()
    assert listed["count"] == 1
    assert listed["servers"][0]["authorization"] == "configured"
    raw = json.loads(managed_mcp.REGISTRY_FILE.read_text())
    assert raw["example"]["authorization"] == "secret-token"


def test_duplicate_name_is_actionable(isolated_registry):
    managed_mcp.install("https://one.example/mcp", name="same")
    with pytest.raises(managed_mcp.ManagedMCPError, match="already exists"):
        managed_mcp.install("https://two.example/mcp", name="same")


def test_github_explicit_command_uses_stdio(isolated_registry, monkeypatch):
    def fake_run(argv, cwd=None):
        if argv[:3] == ["git", "clone", "--depth"]:
            source_dir = managed_mcp.MANAGED_ROOT / "demo" / "source"
            source_dir.mkdir(parents=True)
        return ""

    monkeypatch.setattr(managed_mcp, "_run", fake_run)
    result = managed_mcp.install(
        "https://github.com/example/demo",
        name="demo",
        command="python server.py --stdio",
    )
    assert result["transport"] == "stdio"
    assert result["command"] == ["python", "server.py", "--stdio"]
    assert result["runtime"] == "custom"


def test_remove_archives_local_server(isolated_registry):
    managed_mcp.install("https://mcp.example.com/mcp", name="remote")
    local = managed_mcp.MANAGED_ROOT / "remote"
    local.mkdir(parents=True)
    (local / "data.txt").write_text("keep me")
    result = managed_mcp.remove("remote")
    assert result["removed"] == "remote"
    assert result["recoverable_from"]
    assert not local.exists()
    assert managed_mcp.list_servers()["count"] == 0


@pytest.mark.parametrize(
    "source",
    ["", "not-a-url", "file:///tmp/server", "https://github.com/owner/repo/tree/main"],
)
def test_invalid_source_rejected(isolated_registry, source):
    with pytest.raises(managed_mcp.ManagedMCPError):
        managed_mcp.install(source)
