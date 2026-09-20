"""Transactional update primitives.

This module deliberately does not fetch or install a release yet. It defines the
local safety boundary first: snapshot mutable config, run staged operations,
validate, and restore the snapshot if a later stage fails.
"""
from __future__ import annotations
import json, os, shutil, tempfile, time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from .config_schema import CONFIG_SCHEMA_VERSION

@dataclass(frozen=True)
class Snapshot:
    root: Path
    manifest: Path

def create_snapshot(paths: Iterable[Path], destination: Path | None=None) -> Snapshot:
    root=destination or Path(tempfile.mkdtemp(prefix='termux-mcp-update-'))
    root.mkdir(parents=True,exist_ok=True); entries=[]
    for i,src in enumerate(map(Path,paths)):
        if not src.exists():
            entries.append({'source':str(src),'exists':False}); continue
        target=root/f'item-{i}'
        if src.is_dir(): shutil.copytree(src,target)
        else: shutil.copy2(src,target)
        entries.append({'source':str(src),'exists':True,'is_dir':src.is_dir(),'snapshot':target.name})
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps({'created_at':int(time.time()),'config_schema':CONFIG_SCHEMA_VERSION,'entries':entries},indent=2)+'\n',encoding='utf-8')
    return Snapshot(root,manifest)

def restore_snapshot(snapshot: Snapshot) -> None:
    data=json.loads(snapshot.manifest.read_text(encoding='utf-8'))
    for e in data['entries']:
        dst=Path(e['source'])
        if not e['exists']:
            if dst.is_dir(): shutil.rmtree(dst)
            elif dst.exists(): dst.unlink()
            continue
        src=snapshot.root/e['snapshot']
        if dst.is_dir(): shutil.rmtree(dst)
        elif dst.exists(): dst.unlink()
        dst.parent.mkdir(parents=True,exist_ok=True)
        if e['is_dir']: shutil.copytree(src,dst)
        else: shutil.copy2(src,dst)

def run_transaction(*, mutable_paths: Iterable[Path], install: Callable[[],None], migrate: Callable[[],None], validate: Callable[[],None], snapshot_dir: Path|None=None):
    snap=create_snapshot(mutable_paths,snapshot_dir); stage='install'
    try:
        install(); stage='migrate'; migrate(); stage='validate'; validate()
    except Exception as exc:
        restore_snapshot(snap)
        return {'ok':False,'failed_stage':stage,'rolled_back':True,'error':str(exc),'snapshot':str(snap.root)}
    return {'ok':True,'failed_stage':None,'rolled_back':False,'snapshot':str(snap.root)}
