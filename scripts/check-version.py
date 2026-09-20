#!/usr/bin/env python3
"""Fail when canonical package version metadata disagrees."""
from __future__ import annotations
import argparse, ast, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def pyproject_version():
    text=(ROOT/'pyproject.toml').read_text(encoding='utf-8')
    m=re.search(r'^version\s*=\s*["\']([^"\']+)["\']\s*$',text,re.M)
    if not m: raise SystemExit('cannot find [project].version in pyproject.toml')
    return m.group(1)
def init_version():
    tree=ast.parse((ROOT/'termux_mcp/__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit('cannot find termux_mcp.__version__')
def origin_tags():
    try:
        out=subprocess.check_output(['git','ls-remote','--tags','--refs','origin'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL)
    except Exception: return []
    return sorted(line.split('refs/tags/',1)[1] for line in out.splitlines() if 'refs/tags/' in line)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--release-tag'); args=ap.parse_args()
    canonical=pyproject_version(); mirror=init_version(); errors=[]
    if mirror!=canonical: errors.append(f'__version__={mirror!r} != canonical={canonical!r}')
    if args.release_tag and args.release_tag!=f'v{canonical}': errors.append(f'release tag {args.release_tag!r} != v{canonical}')
    print(f'canonical_version={canonical}'); print(f'package_version={mirror}')
    if args.release_tag: print(f'release_tag={args.release_tag}')
    print('origin_release_tags='+(','.join(origin_tags()) or '(unavailable)'))
    if errors:
        for e in errors: print('ERROR: '+e,file=sys.stderr)
        return 1
    print('version_consistency=OK'); return 0
if __name__=='__main__': raise SystemExit(main())
