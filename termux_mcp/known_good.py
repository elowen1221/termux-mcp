"""Known-good application state for transactional updates."""
from __future__ import annotations
import json, shutil, subprocess, time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE=Path.home()/'.local/state/termux-mcp/known-good.json'
@dataclass(frozen=True)
class KnownGood:
    version: str
    revision: str
    config_schema: int
    recorded_at: int

def current_revision(repo: Path)->str:
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
def write_known_good(state:KnownGood,path:Path=DEFAULT_STATE):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(state.__dict__,indent=2)+'\n',encoding='utf-8'); tmp.replace(path)
def read_known_good(path:Path=DEFAULT_STATE)->KnownGood|None:
    if not path.exists(): return None
    return KnownGood(**json.loads(path.read_text(encoding='utf-8')))
def make_known_good(version,revision,config_schema): return KnownGood(version,revision,config_schema,int(time.time()))

def snapshot_application(repo:Path,destination:Path)->Path:
    """Create a local git bundle containing HEAD and reachable history."""
    destination.parent.mkdir(parents=True,exist_ok=True)
    subprocess.check_call(['git','bundle','create',str(destination),'HEAD'],cwd=repo)
    return destination

def restore_application(repo:Path,bundle:Path,revision:str):
    """Restore tracked application files to a snapshotted revision.

    Caller is responsible for ensuring this is a dedicated managed checkout and
    for preserving user mutable data separately.
    """
    subprocess.check_call(['git','bundle','verify',str(bundle)],cwd=repo,stdout=subprocess.DEVNULL)
    subprocess.check_call(['git','fetch',str(bundle),revision],cwd=repo,stdout=subprocess.DEVNULL)
    subprocess.check_call(['git','reset','--hard',revision],cwd=repo,stdout=subprocess.DEVNULL)
