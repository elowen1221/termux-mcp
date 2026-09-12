import argparse
import io

from termux_mcp import config, onboarding


def _args(**updates):
    values = {
        "client": None,
        "permissions": None,
        "tunnel": "auto",
        "no_tunnel": False,
        "non_interactive": False,
        "force": False,
    }
    values.update(updates)
    return argparse.Namespace(**values)


def test_interactive_setup_is_one_straight_flow(monkeypatch):
    chosen = {}
    monkeypatch.setattr(config, "SETUP_COMPLETE", False)
    monkeypatch.setattr(config, "ensure_token", lambda: "token")
    monkeypatch.setattr(
        config,
        "save_user_preferences",
        lambda client, permissions: chosen.update(
            client=client, permissions=permissions
        ),
    )
    monkeypatch.setattr(config, "get_public_url", lambda: "https://cute.example")
    output = io.StringIO()
    rc = onboarding.run_setup(
        _args(),
        lambda args: 0,
        input_stream=io.StringIO("2\n2\n"),
        output=output,
    )
    text = output.getvalue()
    assert rc == 0
    assert chosen == {"client": "claude", "permissions": "full"}
    assert "( Ꙭ)" in text
    assert "https://cute.example/mcp" in text
    assert "接下来直接在对话框" in text


def test_noninteractive_setup_has_sensible_defaults(monkeypatch):
    chosen = {}
    monkeypatch.setattr(config, "SETUP_COMPLETE", False)
    monkeypatch.setattr(config, "ensure_token", lambda: "token")
    monkeypatch.setattr(
        config,
        "save_user_preferences",
        lambda client, permissions: chosen.update(
            client=client, permissions=permissions
        ),
    )
    monkeypatch.setattr(config, "get_public_url", lambda: "")
    rc = onboarding.run_setup(
        _args(non_interactive=True, no_tunnel=True),
        lambda args: 0,
        output=io.StringIO(),
    )
    assert rc == 0
    assert chosen == {"client": "chatgpt", "permissions": "standard"}
