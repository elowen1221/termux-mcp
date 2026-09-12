import argparse, io
from termux_mcp import config, onboarding

def _args(**u):
    v={"client":None,"permissions":None,"tunnel":"auto","no_tunnel":False,"non_interactive":False,"force":False}; v.update(u); return argparse.Namespace(**v)
def _mock(monkeypatch,chosen,url="https://cute.example"):
    monkeypatch.setattr(config,"SETUP_COMPLETE",False); monkeypatch.setattr(config,"ensure_token",lambda:"token")
    monkeypatch.setattr(config,"save_user_preferences",lambda c,p:chosen.update(client=c,permissions=p))
    monkeypatch.setattr(config,"save_connection_preference",lambda m,v="":chosen.update(mode=m,value=v))
    monkeypatch.setattr(config,"get_public_url",lambda:url)

def test_default_free_flow(monkeypatch):
    c={}; _mock(monkeypatch,c); started={}; out=io.StringIO()
    rc=onboarding.run_setup(_args(),lambda a:started.update(no_tunnel=a.no_tunnel) or 0,io.StringIO("\n\n\n"),out)
    assert rc==0 and c=={"client":"chatgpt","permissions":"standard","mode":"free","value":""}
    assert started["no_tunnel"] is False and "一路按 Enter" in out.getvalue() and "https://cute.example/mcp" in out.getvalue()

def test_custom_domain_is_saved_but_not_claimed_live(monkeypatch):
    c={}; _mock(monkeypatch,c,""); started={}; out=io.StringIO()
    rc=onboarding.run_setup(_args(),lambda a:started.update(no_tunnel=a.no_tunnel) or 0,io.StringIO("\n\n2\nexample.com\n\n"),out)
    text=out.getvalue(); assert rc==0
    assert c["mode"]=="domain" and c["value"]=="termux.example.com" and started["no_tunnel"] is True
    assert "https://termux.example.com/mcp" in text and "还没有宣称它已经能访问" in text and "不会擅自修改 DNS" in text

def test_custom_subdomain(monkeypatch):
    c={}; _mock(monkeypatch,c,""); out=io.StringIO()
    onboarding.run_setup(_args(),lambda a:0,io.StringIO("1\n1\n2\nexample.com\nmcp\n"),out)
    assert c["value"]=="mcp.example.com"

def test_invalid_domain_reprompts(monkeypatch):
    c={}; _mock(monkeypatch,c,""); out=io.StringIO()
    onboarding.run_setup(_args(),lambda a:0,io.StringIO("\n\n2\nhttps://bad/mcp\nexample.org\n\n"),out)
    assert c["value"]=="termux.example.org" and "不像域名" in out.getvalue()

def test_existing_external_https(monkeypatch):
    c={}; _mock(monkeypatch,c,""); started={}; out=io.StringIO()
    onboarding.run_setup(_args(),lambda a:started.update(no_tunnel=a.no_tunnel) or 0,io.StringIO("\n\n3\nhttp://bad\nhttps://mcp.example.com/mcp\n"),out)
    assert c["mode"]=="external" and c["value"]=="https://mcp.example.com" and started["no_tunnel"] is True
    assert "请填完整 HTTPS" in out.getvalue()

def test_local_and_noninteractive(monkeypatch):
    c={}; _mock(monkeypatch,c,""); started={}
    onboarding.run_setup(_args(),lambda a:started.update(no_tunnel=a.no_tunnel) or 0,io.StringIO("\n\n4\n"),io.StringIO())
    assert c["mode"]=="local" and started["no_tunnel"] is True
    c={}; _mock(monkeypatch,c,"")
    assert onboarding.run_setup(_args(non_interactive=True,no_tunnel=True),lambda a:0,output=io.StringIO())==0
    assert c["client"]=="chatgpt" and c["permissions"]=="standard" and c["mode"]=="local"
