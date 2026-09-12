import os
from termux_mcp import config, relay, tunnel


def test_relay_identity_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.env"))
    monkeypatch.setattr(config, "_FILE_VALUES", {})
    first = relay.ensure_identity()
    second = relay.ensure_identity()
    assert first == second
    assert len(first[0]) >= 12
    assert len(first[1]) >= 32
    assert (tmp_path / "config.env").stat().st_mode & 0o077 == 0


def test_relay_public_url_is_stable_path(monkeypatch):
    monkeypatch.setattr(relay, "RELAY_BASE", "https://relay.example.com")
    assert relay.public_url("device-abcdefghijkl") == "https://relay.example.com/d/device-abcdefghijkl"


def test_relay_url_validation(monkeypatch):
    monkeypatch.setattr(relay, "RELAY_BASE", "https://relay.example.com")
    assert tunnel._is_valid_tunnel_url("relay", "https://relay.example.com/d/device-abcdefghijkl")
    assert not tunnel._is_valid_tunnel_url("relay", "https://evil.example/d/device-abcdefghijkl")
    assert not tunnel._is_valid_tunnel_url("relay", "https://relay.example.com/admin")


def test_relay_provider_registered():
    assert isinstance(tunnel.get_provider("relay"), tunnel.RelayProvider)


def test_relay_requires_explicit_base(monkeypatch):
    monkeypatch.setattr(relay, "RELAY_BASE", "")
    try:
        relay.public_url("device-abcdefghijkl")
    except RuntimeError as exc:
        assert "self-hosted" in str(exc)
    else:
        raise AssertionError("relay must not silently use maintainer infrastructure")
