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
