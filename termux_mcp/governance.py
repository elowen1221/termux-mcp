"""Local component registry and desired-state inspection."""
from __future__ import annotations
import json, os, socket, subprocess
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_REGISTRY = Path.home()/'.config/termux-mcp/components.json'
def load_registry(path=None):
    p=Path(path or os.environ.get('TERMUX_MCP_COMPONENTS',DEFAULT_REGISTRY)).expanduser()
    with p.open(encoding='utf-8') as f: return json.load(f)['components']
def tcp_reachable(url,timeout=1.0):
    u=urlparse(url); port=u.port or (443 if u.scheme=='https' else 80)
    try:
        with socket.create_connection((u.hostname,port),timeout): return True
    except OSError: return False
def component_state(name,c):
    if c.get('probe')=='tcp' and c.get('endpoint'): return 'running' if tcp_reachable(c['endpoint']) else 'stopped'
    if name=='core' and c.get('endpoint'): return 'running' if tcp_reachable(c['endpoint']) else 'stopped'
    if name=='ingress.cloudflare':
        import subprocess
        return 'running' if subprocess.run(['pgrep','-f','^cloudflared tunnel'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0 else 'stopped'
    if name=='observability.telemetry':
        import subprocess
        return 'running' if subprocess.run(['pgrep','-f','walnut-telemetry/bin/collector.sh'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0 else 'stopped'
    return 'unknown'
def inspect_component(name,registry=None):
    cs=registry or load_registry(); c=cs[name].copy(); c['id']=name; c['actual_state']=component_state(name,c); return c
def reconcile(registry=None):
    cs=registry or load_registry(); out=[]
    for name,c in cs.items():
        actual=component_state(name,c); desired=c.get('desired_state','stopped')
        out.append({'id':name,'desired':desired,'actual':actual,'drift':actual!='unknown' and actual!=desired})
    return out


def topology(registry=None):
    cs=registry or load_registry(); rows=[]
    for name,c in cs.items():
        actual=component_state(name,c)
        desired=c.get("desired_state","stopped")
        rows.append({"id":name,"class":c.get("class","unknown"),"owner":c.get("owner","unknown"),"required":bool(c.get("required")),"depends_on":c.get("depends_on",[]),"desired":desired,"actual":actual,"drift":actual!="unknown" and actual!=desired})
    return rows

def recovery_plan(name, registry=None):
    cs=registry or load_registry(); c=cs[name]; mode=c.get("recover_mode","manual"); desired=c.get("desired_state","stopped")
    if mode=="external_manual": return {"allowed":False,"mode":mode,"reason":c.get("recover_hint","External/manual recovery required.")}
    if mode=="on_demand" and desired!="running": return {"allowed":False,"mode":mode,"reason":"Component is intentionally stopped; start explicitly when needed."}
    action=c.get("recover")
    if not action: return {"allowed":False,"mode":mode,"reason":"No registered recovery action; refusing to guess."}
    return {"allowed":True,"mode":mode,"action":action}


def recover_component(name, registry=None, execute=False):
    cs=registry or load_registry()
    plan=recovery_plan(name,cs)
    if not execute or not plan.get("allowed"):
        return plan
    action=os.path.expanduser(plan["action"])
    result=subprocess.run(['/data/data/com.termux/files/usr/bin/bash','-lc',action])
    return {**plan,"executed":True,"returncode":result.returncode}
