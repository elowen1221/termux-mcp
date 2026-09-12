import argparse
import io

from termux_mcp import config, onboarding


def _args(**updates):
    values = {"client": None, "permissions": None, "tunnel": "auto", "no_tunnel": False, "non_interactive": False, "force": False}
    values.update(updates)
    return argparse.Namespace(**values)


def _mock_config(monkeypatch, chosen, url="https://cute.example"):
    monkeypatch.setattr(config, "SETUP_COMPLETE", False)
    monkeypatch.setattr(config, "ensure_token", lambda: "token")
    monkeypatch.setattr(config, "save_user_preferences", lambda client, permissions: chosen.update(client=client, permissions=permissions))
    monkeypatch.setattr(config, "get_public_url", lambda: url)


def test_interactive_setup_is_beginner_first(monkeypatch):
    chosen = {}; _mock_config(monkeypatch, chosen)
    started = {}
    output = io.StringIO()
    rc = onboarding.run_setup(_args(), lambda args: started.update(no_tunnel=args.no_tunnel, tunnel=args.tunnel) or 0, input_stream=io.StringIO("2\n2\ny\n"), output=output)
    text = output.getvalue()
    assert rc == 0
    assert chosen == {"client": "claude", "permissions": "read-only"}
    assert started == {"no_tunnel": False, "tunnel": "auto"}
    assert "不需要懂 Linux" in text
    assert "[1/3]" in text and "[2/3]" in text and "[3/3]" in text
    assert "https://cute.example/mcp" in text
    assert "不用把终端里的 Auth token 发给任何人" in text
    assert "termux-mcp url" in text


def test_beginner_can_choose_local_only(monkeypatch):
    chosen = {}; _mock_config(monkeypatch, chosen, "")
    started = {}
    output = io.StringIO()
    rc = onboarding.run_setup(_args(), lambda args: started.update(no_tunnel=args.no_tunnel) or 0, input_stream=io.StringIO("\n\nn\n"), output=output)
    assert rc == 0
    assert chosen == {"client": "chatgpt", "permissions": "standard"}
    assert started["no_tunnel"] is True
    assert "127.0.0.1" in output.getvalue()
    assert "只在手机本机使用" in output.getvalue()


def test_noninteractive_setup_has_sensible_defaults(monkeypatch):
    chosen = {}; _mock_config(monkeypatch, chosen, "")
    rc = onboarding.run_setup(_args(non_interactive=True, no_tunnel=True), lambda args: 0, output=io.StringIO())
    assert rc == 0
    assert chosen == {"client": "chatgpt", "permissions": "standard"}


def test_yes_no_reprompts_invalid_value():
    values = iter(["what", "n"])
    assert onboarding._yes_no("?", True, lambda _: next(values)) is False
