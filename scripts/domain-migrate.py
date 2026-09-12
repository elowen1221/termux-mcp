#!/usr/bin/env python3
"""Preview or apply local URL rewrites for a Termux-MCP domain migration."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from termux_mcp.domain_migration import apply_url_rewrites, plan_url_rewrites


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate known Termux-MCP public URLs safely")
    parser.add_argument("old_domain")
    parser.add_argument("new_domain")
    parser.add_argument("--apply", action="store_true", help="write changes; default is preview only")
    args = parser.parse_args()

    plans = plan_url_rewrites(args.old_domain, args.new_domain)
    if not plans:
        print("No known project/config URLs need migration.")
        return 0

    print("Local URL migration preview:" if not args.apply else "Applying local URL migration:")
    for plan in plans:
        label = "private config" if plan.secret else "project file"
        print(f"  {plan.path}  [{label}, {plan.replacements} replacement(s)]")

    if not args.apply:
        print("No files changed. Re-run with --apply after reviewing the plan.")
        return 0

    results = apply_url_rewrites(args.old_domain, args.new_domain)
    print(f"Updated {len(results)} file(s); each original was backed up beside the file.")
    print("Restart affected services and run health checks before switching clients.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
