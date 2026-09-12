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
        "  - hostname: termux.walnutnest.buzz\n"
        "    service: http://127.0.0.1:8765\n"
        "  - hostname: weather.walnutnest.buzz\n"
        "    service: http://127.0.0.1:8876\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )

    planned = named_tunnel.plan_domain_migration(
        "newnest.xyz", path=str(cfg), from_domain="walnutnest.buzz"
    )
    assert [(old.hostname, new.hostname, new.service) for old, new in planned] == [
        ("termux.walnutnest.buzz", "termux.newnest.xyz", "http://127.0.0.1:8765"),
        ("weather.walnutnest.buzz", "weather.newnest.xyz", "http://127.0.0.1:8876"),
    ]
    assert "walnutnest.buzz" in cfg.read_text(encoding="utf-8")


def test_migrate_ingress_domain_is_backed_up_and_validated(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.walnutnest.buzz\n"
        "    service: http://127.0.0.1:8765\n"
        "  - hostname: alpaca.walnutnest.buzz\n"
        "    service: http://127.0.0.1:8877\n"
        "  - service: http_status:404\n",
        encoding="utf-8",
    )
    calls = []

    def runner(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="OK", stderr="")

    backup, planned = named_tunnel.migrate_ingress_domain(
        "next.example", path=str(cfg), from_domain="walnutnest.buzz", runner=runner
    )
    text = cfg.read_text(encoding="utf-8")
    assert "termux.next.example" in text
    assert "alpaca.next.example" in text
    assert "walnutnest.buzz" not in text
    assert Path(backup).is_file()
    assert len(planned) == 2
    assert calls == [["cloudflared", "tunnel", "ingress", "validate"]]


def test_domain_migration_validation_failure_restores_original(tmp_path):
    cfg = tmp_path / "config.yml"
    original = (
        "tunnel: abc\ningress:\n"
        "  - hostname: termux.walnutnest.buzz\n"
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
            from_domain="walnutnest.buzz",
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
