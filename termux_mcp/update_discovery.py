"""Read-only release discovery for the fork's own origin remote."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass, asdict
from packaging.version import InvalidVersion, Version

@dataclass(frozen=True)
class UpdateCheck:
    installed: str
    latest_release: str | None
    latest_tag: str | None
    update_available: bool
    status: str
    detail: str

    def as_dict(self): return asdict(self)

def _parse_product_tag(tag: str):
    if not tag.startswith('v'): return None
    try: return Version(tag[1:])
    except InvalidVersion: return None

DEFAULT_RELEASE_REMOTE='https://github.com/elowen1221/termux-mcp.git'

def origin_release_tags(remote: str=DEFAULT_RELEASE_REMOTE) -> list[str]:
    out=subprocess.check_output(['git','ls-remote','--tags','--refs',remote],text=True,stderr=subprocess.DEVNULL)
    tags=[]
    for line in out.splitlines():
        if 'refs/tags/' not in line: continue
        tag=line.split('refs/tags/',1)[1]
        if _parse_product_tag(tag) is not None: tags.append(tag)
    return sorted(set(tags),key=lambda t:_parse_product_tag(t))

def check_updates(installed: str, remote: str=DEFAULT_RELEASE_REMOTE) -> UpdateCheck:
    current=Version(installed)
    tags=origin_release_tags(remote)
    if not tags:
        return UpdateCheck(installed,None,None,False,'no_release_baseline','No product release tags were found on origin.')
    latest_tag=tags[-1]; latest=_parse_product_tag(latest_tag)
    assert latest is not None
    if latest > current:
        return UpdateCheck(installed,str(latest),latest_tag,True,'update_available',f'{latest_tag} is newer than installed {installed}.')
    if latest == current:
        return UpdateCheck(installed,str(latest),latest_tag,False,'up_to_date',f'Installed {installed} matches the latest origin release.')
    return UpdateCheck(installed,str(latest),latest_tag,False,'installed_ahead_of_release_baseline',f'Installed {installed} is newer than the latest origin release tag {latest_tag}; no downgrade is proposed.')
