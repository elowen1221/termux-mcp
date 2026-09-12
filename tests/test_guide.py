import io
from termux_mcp import config, guide, process

def test_guide_is_screenshot_friendly_and_warns_about_token(monkeypatch):
    monkeypatch.setattr(config,"CONNECTION_MODE","free"); monkeypatch.setattr(config,"CONNECTION_VALUE","")
    monkeypatch.setattr(config,"get_public_url",lambda:"https://cute.example"); monkeypatch.setattr(process,"is_running",lambda:True)
    out=io.StringIO(); assert guide.run_guide(out)==0; text=out.getvalue()
    for command,_ in guide.COMMANDS: assert command in text
    assert "直接截个图" in text and "token --show" in text and "不要截图分享" in text
    assert "https://cute.example/mcp" in text

def test_guide_respects_domain_route(monkeypatch):
    monkeypatch.setattr(config,"CONNECTION_MODE","domain"); monkeypatch.setattr(config,"CONNECTION_VALUE","termux.example.com")
    monkeypatch.setattr(config,"get_public_url",lambda:""); monkeypatch.setattr(process,"is_running",lambda:True)
    out=io.StringIO(); guide.run_guide(out); text=out.getvalue()
    assert "termux.example.com" in text and "不会擅自修改" in text and "Named Tunnel" in text
