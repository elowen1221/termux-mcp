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
def test_flatten_ui_extracts_visible_nodes():
 tree={'class':'root','children':[{'text':'hello','desc':'null','bounds':[1,2,3,4],'children':[]}]}
 assert a._flatten_ui(tree)[0]['text']=='hello'
def test_browse_returns_semantic_ui(monkeypatch):
 r=registry(); r['xhs']['capabilities'].append('browse')
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 monkeypatch.setattr(a.android_bridge,'current_ui',lambda depth:{'ok':True,'data':{'children':[{'desc':'笔记 测试 12赞','bounds':[0,0,1,1]}]}})
 out=a.browse('xhs',r); assert out['ok'] and out['items'][0]['desc']=='笔记 测试 12赞'
def test_act_refuses_wrong_foreground(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'other.app'}})
 out=a.act('xhs','like',desc='赞',registry=registry()); assert not out['ok'] and out['expected_package']=='com.xingin.xhs'
def test_act_like_requires_semantic_selector(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 out=a.act('xhs','like',registry=registry()); assert not out['ok'] and 'semantic selector' in out['error']
def test_act_like_uses_selector(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 monkeypatch.setattr(a.android_bridge,'click_selector',lambda **kwargs:{'ok':True,'data':kwargs})
 out=a.act('xhs','like',desc='赞',registry=registry()); assert out['ok'] and out['result']['data']['desc']=='赞'
def test_discover_classifies_semantic_targets(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 monkeypatch.setattr(a.android_bridge,'current_ui',lambda depth:{'ok':True,'data':{'children':[{'desc':'搜索','id':'search','clickable':True},{'desc':'点赞','id':'like_btn','clickable':True},{'text':'一条笔记'}]}})
 out=a.discover('xhs',registry()); assert [x['role'] for x in out['targets']]==['search','like','content']
def test_discover_refuses_other_foreground(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.openai.chatgpt'}})
 out=a.discover('xhs',registry()); assert not out['ok'] and out['foreground_package']=='com.openai.chatgpt'
def test_act_search_requires_semantic_selector(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 r=registry(); r['xhs']['capabilities'].append('search')
 out=a.act('xhs','search',registry=r); assert not out['ok'] and 'semantic selector' in out['error']
def test_act_search_clicks_semantic_selector(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 monkeypatch.setattr(a.android_bridge,'click_selector',lambda **kwargs:{'ok':True,'data':kwargs})
 r=registry(); r['xhs']['capabilities'].append('search')
 out=a.act('xhs','search',desc='搜索',registry=r); assert out['ok'] and out['result']['data']['desc']=='搜索'
def test_discover_does_not_treat_like_count_as_like_button(monkeypatch):
 monkeypatch.setattr(a.android_bridge,'current_context',lambda:{'ok':True,'data':{'package':'com.xingin.xhs'}})
 monkeypatch.setattr(a.android_bridge,'current_ui',lambda depth:{'ok':True,'data':{'children':[{'class':'android.widget.FrameLayout','desc':'笔记 一个标题 来自用户 535赞','clickable':False},{'class':'android.widget.Button','desc':'点赞','clickable':True}]}})
 out=a.discover('xhs',registry()); assert [x['role'] for x in out['targets']]==['content','like']
