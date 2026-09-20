"""Safety checks before an updater is allowed to mutate application files."""
from __future__ import annotations
import json, subprocess
from dataclasses import dataclass
from pathlib import Path

MARKER='.termux-mcp-managed.json'
@dataclass(frozen=True)
class InstallAssessment:
    managed: bool
    clean: bool
    revision: str|None
    marker_revision: str|None
    rollback_safe: bool
    reasons: tuple[str,...]

def _git(repo,*args):
    return subprocess.check_output(['git',*args],cwd=repo,text=True,stderr=subprocess.DEVNULL).strip()
def mark_managed_install(repo:Path,version:str,revision:str):
    p=repo/MARKER; p.write_text(json.dumps({'managed_by':'termux-mcp','version':version,'revision':revision},indent=2)+'\n',encoding='utf-8'); return p
def assess_install(repo:Path)->InstallAssessment:
    repo=Path(repo); reasons=[]; marker=repo/MARKER; managed=False; marker_rev=None
    try:
        data=json.loads(marker.read_text(encoding='utf-8')); managed=data.get('managed_by')=='termux-mcp'; marker_rev=data.get('revision')
    except Exception: reasons.append('managed-install marker missing or invalid')
    try: revision=_git(repo,'rev-parse','HEAD')
    except Exception:
        revision=None; reasons.append('not a readable Git checkout')
    try: clean=(_git(repo,'status','--porcelain')=='')
    except Exception: clean=False
    if not clean: reasons.append('working tree has user/uncommitted changes')
    if managed and revision and marker_rev and revision!=marker_rev: reasons.append('HEAD differs from managed-install revision')
    safe=managed and clean and revision is not None and marker_rev==revision
    return InstallAssessment(managed,clean,revision,marker_rev,safe,tuple(reasons))
