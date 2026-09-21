from termux_mcp import app_registry as a

def registry():
 return {'pdd':{'label':'拼多多','category':'shopping','package':'com.xunmeng.pinduoduo','driver':'android_ui','capabilities':['launch','browse'],'permissions':{'payment':'deny'}},'xhs':{'label':'小红书','category':'social','package':'com.xingin.xhs','driver':'android_ui','capabilities':['like'],'permissions':{'like':'allow','comment':'deny'}}}

def test_list_category(): assert [x['id'] for x in a.list_apps('social',registry())]==['xhs']
def test_inspect_preserves_policy(): assert a.inspect('pdd',registry())['permissions']['payment']=='deny'
def test_doctor_requires_bridge_and_package(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'status',lambda:{'accessibility_ready':True})
 monkeypatch.setattr(a.android_bridge,'find_app',lambda q:{'matches':[{'label':'拼多多','package':'com.xunmeng.pinduoduo'}]})
 assert a.doctor('pdd',registry())['ready'] is True
def test_authorize_read_only_default(): assert a.authorize('pdd','browse',registry())['allowed'] is True
def test_authorize_denied_payment_unregistered(): assert a.authorize('pdd','payment',registry())['allowed'] is False
def test_authorize_like_explicit_allow(): assert a.authorize('xhs','like',registry())['allowed'] is True
def test_launch_uses_registered_package(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'open_app',lambda package:{'opened':True,'package':package})
 out=a.launch('pdd',registry()); assert out['ok'] and out['result']['package']=='com.xunmeng.pinduoduo'
