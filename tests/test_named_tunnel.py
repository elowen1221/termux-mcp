"""Tests for safe Cloudflare named-tunnel configuration."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from termux_mcp import named_tunnel


def test_add_ingress_is_validated_backed_up_and_idempotent(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.example.com\n"
        "    service: http://127.0.0.1:8765\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    calls = []

    def runner(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    backup = named_tunnel.add_ingress(
        "weather.example.com", 8876, path=str(cfg), runner=runner
    )
    text = cfg.read_text(encoding="utf-8")
    assert "hostname: weather.example.com" in text
    assert text.index("weather.example.com") < text.index("http_status:404")
    assert Path(backup).is_file()
    assert len(calls) == 1
    assert named_tunnel.add_ingress(
        "weather.example.com", 8876, path=str(cfg), runner=runner
    ) == ""


def test_validation_failure_restores_original(tmp_path):
    cfg = tmp_path / "config.yml"
    original = "tunnel: abc\ningress:\n  - service: http_status:404\n"
    cfg.write_text(original, encoding="utf-8")

    def runner(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="bad ingress")

    with pytest.raises(RuntimeError, match="restored backup"):
        named_tunnel.add_ingress(
            "weather.example.com", 8876, path=str(cfg), runner=runner
        )
    assert cfg.read_text(encoding="utf-8") == original


def test_existing_hostname_with_other_port_is_rejected(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "ingress:\n"
        "  - hostname: weather.example.com\n"
        "    service: http://127.0.0.1:8876\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="already routes"):
        named_tunnel.add_ingress(
            "weather.example.com", 9000, path=str(cfg), validate=False
        )


def test_route_dns_retries_transient_failure():
    results = iter([
        SimpleNamespace(returncode=1, stdout="", stderr="timeout"),
        SimpleNamespace(returncode=0, stdout="added", stderr=""),
    ])
    sleeps = []
    result = named_tunnel.route_dns(
        "my-tunnel",
        "weather.example.com",
        runner=lambda *a, **k: next(results),
        sleeper=sleeps.append,
    )
    assert result.returncode == 0
    assert sleeps == [1.0]


def test_plan_domain_migration_preserves_subdomains_and_services(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.old.example\n"
        "    service: http://127.0.0.1:8765\n"
        "  - hostname: weather.old.example\n"
        "    service: http://127.0.0.1:8876\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )

    planned = named_tunnel.plan_domain_migration(
        "new.example", path=str(cfg), from_domain="old.example"
    )
    assert [(old.hostname, new.hostname, new.service) for old, new in planned] == [
        ("termux.old.example", "termux.new.example", "http://127.0.0.1:8765"),
        ("weather.old.example", "weather.new.example", "http://127.0.0.1:8876"),
    ]
    assert "old.example" in cfg.read_text(encoding="utf-8")


def test_migrate_ingress_domain_is_backed_up_and_validated(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.old.example\n"
        "    service: http://127.0.0.1:8765\n"
        "  - hostname: alpaca.old.example\n"
        "    service: http://127.0.0.1:8877\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    calls = []

    def runner(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    backup, planned = named_tunnel.migrate_ingress_domain(
        "next.example", path=str(cfg), from_domain="old.example", runner=runner
    )
    text = cfg.read_text(encoding="utf-8")
    assert "termux.next.example" in text
    assert "alpaca.next.example" in text
    assert "old.example" not in text
    assert Path(backup).is_file()
    assert len(planned) == 2
    assert calls == [["cloudflared", "tunnel", "ingress", "validate"]]


def test_domain_migration_validation_failure_restores_original(tmp_path):
    cfg = tmp_path / "config.yml"
    original = (
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.old.example\n"
        "    service: http://127.0.0.1:8765\n"
        "  - service: http_status:404\n"
    )
    cfg.write_text(original, encoding="utf-8")

    def runner(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="bad ingress")

    with pytest.raises(RuntimeError, match="restored backup"):
        named_tunnel.migrate_ingress_domain(
            "next.example",
            path=str(cfg),
            from_domain="old.example",
            runner=runner,
        )
    assert cfg.read_text(encoding="utf-8") == original


def test_plan_domain_migration_requires_source_for_mixed_domains(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "ingress:\n"
        "  - hostname: one.example.com\n"
        "    service: http://127.0.0.1:8765\n"
        "  - hostname: two.other.net\n"
        "    service: http://127.0.0.1:8876\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="--from-domain"):
        named_tunnel.plan_domain_migration("next.example", path=str(cfg))

def test_inspect_cloudflare_is_side_effect_free(monkeypatch, tmp_path):
    cert = tmp_path / ".cloudflared" / "cert.pem"
    cert.parent.mkdir(); cert.write_text("x")
    cfg = cert.parent / "config.yml"; cfg.write_text("tunnel: abc\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(named_tunnel.shutil, "which", lambda name: "/bin/cloudflared")
    monkeypatch.setattr(named_tunnel, "DEFAULT_CONFIG", str(cfg))
    def runner(*args, **kwargs):
        assert args[0] == ["cloudflared", "tunnel", "list", "--output", "json"]
        return SimpleNamespace(returncode=0, stdout='[{"id":"abc","name":"termux-mcp"}]', stderr="")
    state = named_tunnel.inspect_cloudflare(runner=runner)
    assert state["installed"] is True
    assert state["authenticated"] is True
    assert state["config_exists"] is True
    assert state["tunnels"] == [{"id":"abc","name":"termux-mcp"}]
