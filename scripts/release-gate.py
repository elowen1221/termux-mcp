#!/usr/bin/env python3
"""Fast local release metadata gate; CI runs this before publishing."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run(*cmd):
    print('+',' '.join(map(str,cmd)),flush=True)
    return subprocess.run(cmd,cwd=ROOT).returncode
def main():
    checks=[
        (sys.executable,'scripts/check-version.py'),
        (sys.executable,'-m','pytest','-q','tests/test_release_version.py'),
    ]
    for cmd in checks:
        if run(*cmd): return 1
    required=['CHANGELOG.md','docs/RELEASE_POLICY.md','termux_mcp/config_schema.py']
    missing=[x for x in required if not (ROOT/x).is_file()]
    if missing:
        print('ERROR: missing release metadata: '+', '.join(missing),file=sys.stderr); return 1
    import json, re
    py=(ROOT/'pyproject.toml').read_text(encoding='utf-8')
    version=re.search(r'^version\s*=\s*["\']([^"\']+)',py,re.M).group(1)
    manifest=ROOT/'releases'/f'v{version}.json'
    if manifest.is_file():
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('version')!=version or data.get('tag')!=f'v{version}':
            print('ERROR: release manifest version/tag does not match canonical version',file=sys.stderr); return 1
        if data.get('config_schema') is None:
            print('ERROR: release manifest missing config_schema',file=sys.stderr); return 1
    text=(ROOT/'CHANGELOG.md').read_text(encoding='utf-8')
    if '## [Unreleased]' not in text:
        print('ERROR: CHANGELOG.md has no [Unreleased] section',file=sys.stderr); return 1
    print('release_metadata_gate=OK'); return 0
if __name__=='__main__': raise SystemExit(main())
