from argparse import Namespace
from termux_mcp import cli, config, named_tunnel


def test_domain_guide_discovers_existing_mcp_ingress(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "config.yml"
    cfg.write_text(f"ingress:\n  - hostname: termux.example.com\n    service: http://127.0.0.1:{cli.MCP_PORT}\n  - service: http_status:404\n")
    monkeypatch.setattr(config, "CONNECTION_VALUE", "")
    monkeypatch.setattr(named_tunnel, "inspect_cloudflare", lambda: {"installed": True, "authenticated": True, "config_exists": True, "tunnels": [{"id": "abc", "name": "termux-mcp"}]})
    rc = cli.cmd_domain(Namespace(domain_command="guide", hostname=None, config=str(cfg)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "目标地址：https://termux.example.com/mcp" in out
    assert "已经在 ingress 中" in out
    assert "setup --force" not in out
