"""Declarative Android app capability registry.

This is intentionally separate from infrastructure governance: components say
what keeps Termux-MCP alive; apps say which Android surfaces the agent may use.
"""
from __future__ import annotations
import json
from pathlib import Path
from . import android_bridge

REGISTRY_PATH = Path(__file__).with_name('data') / 'android_apps.json'

def load_registry(path: Path | None = None) -> dict:
    data=json.loads((path or REGISTRY_PATH).read_text(encoding='utf-8'))
    return data['apps']

def list_apps(category: str | None=None, registry: dict | None=None) -> list[dict]:
    apps=registry or load_registry(); rows=[]
    for app_id, app in apps.items():
        if category and app.get('category') != category: continue
        rows.append({'id':app_id, **app})
    return sorted(rows,key=lambda r:(r.get('category',''),r['id']))

def inspect(app_id: str, registry: dict | None=None) -> dict:
    apps=registry or load_registry()
    if app_id not in apps: raise KeyError(app_id)
    return {'id':app_id, **apps[app_id]}

def doctor(app_id: str, registry: dict | None=None) -> dict:
    app=inspect(app_id,registry); package=app['package']
    bridge=android_bridge.status(); installed=False; matched=None
    found=android_bridge.find_app(package)
    for item in found.get('matches',[]):
        candidate=item.get('package') if isinstance(item,dict) else item
        if candidate==package: installed=True; matched=item; break
    return {'id':app_id,'label':app.get('label'),'category':app.get('category'),'package':package,
            'driver':app.get('driver'),'bridge':bridge,'installed':installed,'matched':matched,
            'ready':bool(installed and bridge.get('accessibility_ready')),
            'capabilities':app.get('capabilities',[]),'permissions':app.get('permissions',{})}

SAFE_READ_ACTIONS = {'launch','search','browse','inspect_product','read_reviews','inspect_post'}

def authorize(app_id: str, action: str, registry: dict | None=None) -> dict:
    app=inspect(app_id,registry)
    if action not in app.get('capabilities',[]):
        return {'allowed':False,'decision':'deny','reason':'capability is not registered'}
    policy=app.get('permissions',{}).get(action)
    if policy == 'deny': return {'allowed':False,'decision':'deny','reason':'permission policy denies action'}
    if policy == 'ask': return {'allowed':False,'decision':'ask','reason':'explicit user confirmation required'}
    if policy == 'allow': return {'allowed':True,'decision':'allow'}
    if action in SAFE_READ_ACTIONS: return {'allowed':True,'decision':'allow','reason':'registered read-only capability'}
    return {'allowed':False,'decision':'deny','reason':'no explicit permission for state-changing action'}

def launch(app_id: str, registry: dict | None=None) -> dict:
    app=inspect(app_id,registry); auth=authorize(app_id,'launch',registry)
    if not auth['allowed']: return {'ok':False,'id':app_id,'authorization':auth}
    result=android_bridge.open_app(app['package'])
    return {'ok':bool(result.get('opened')),'id':app_id,'authorization':auth,'result':result}

def _flatten_ui(node) -> list[dict]:
    out=[]
    if isinstance(node,dict):
        if any(k in node for k in ('text','desc','bounds','clickable','editable')):
            out.append({k:node.get(k) for k in ('class','text','desc','id','bounds','clickable','editable') if k in node})
        for child in node.get('children',[]) if isinstance(node.get('children'),list) else []:
            out.extend(_flatten_ui(child))
    elif isinstance(node,list):
        for child in node: out.extend(_flatten_ui(child))
    return out

def browse(app_id: str, registry: dict | None=None, max_depth: int=8) -> dict:
    auth=authorize(app_id,'browse',registry)
    if not auth['allowed']: return {'ok':False,'id':app_id,'authorization':auth}
    app=inspect(app_id,registry); ctx=android_bridge.current_context()
    package=(ctx.get('data') or {}).get('package') if ctx.get('ok') else None
    if package != app['package']:
        opened=launch(app_id,registry)
        if not opened.get('ok'): return {'ok':False,'id':app_id,'authorization':auth,'launch':opened}
    ui=android_bridge.current_ui(max_depth)
    if not ui.get('ok'): return {'ok':False,'id':app_id,'authorization':auth,'ui':ui}
    nodes=_flatten_ui(ui.get('data',{}))
    visible=[]
    for n in nodes:
        text=n.get('text'); desc=n.get('desc')
        if text in (None,'null'): text=None
        if desc in (None,'null'): desc=None
        if text or desc: visible.append({**n,'text':text,'desc':desc})
    return {'ok':True,'id':app_id,'label':app.get('label'),'package':app['package'],
            'authorization':auth,'items':visible,'count':len(visible)}
