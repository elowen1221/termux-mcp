import json
from termux_mcp import governance

def test_load_and_reconcile(tmp_path):
    p=tmp_path/'components.json'; p.write_text(json.dumps({'components':{'x':{'desired_state':'stopped','probe':'tcp','endpoint':'http://127.0.0.1:1'}}}))
    cs=governance.load_registry(p); assert 'x' in cs
    rows=governance.reconcile(cs); assert rows[0]['desired']=='stopped'; assert rows[0]['actual']=='stopped'; assert rows[0]['drift'] is False

def test_inspect_preserves_owner(monkeypatch):
    monkeypatch.setattr(governance,'component_state',lambda n,c:'running')
    x=governance.inspect_component('x',{'x':{'owner':'demo','desired_state':'running'}})
    assert x['owner']=='demo' and x['actual_state']=='running'

def test_recovery_plan_refuses_external():
    p=governance.recovery_plan('bridge',{'bridge':{'recover_mode':'external_manual','recover_hint':'use Android'}})
    assert p['allowed'] is False and p['mode']=='external_manual'

def test_recovery_plan_refuses_stopped_on_demand():
    p=governance.recovery_plan('weather',{'weather':{'recover_mode':'on_demand','desired_state':'stopped'}})
    assert p['allowed'] is False

def test_recovery_plan_registered_action():
    p=governance.recovery_plan('core',{'core':{'recover_mode':'automatic','desired_state':'running','recover':'termux-mcp start --no-tunnel'}})
    assert p['allowed'] is True and 'termux-mcp start' in p['action']

def test_recover_component_plan_only_does_not_execute(monkeypatch):
    def boom(*a,**k): raise AssertionError('must not execute')
    monkeypatch.setattr(governance.subprocess,'run',boom)
    r=governance.recover_component('core',{'core':{'recover_mode':'automatic','desired_state':'running','recover':'echo ok'}},execute=False)
    assert r['allowed'] is True and 'executed' not in r
