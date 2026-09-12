#!/usr/bin/env python3
"""Read-only health check for the workbench's public MCP endpoints."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

SERVICES = {
    "workbench": "termux",
    "weather": "weather",
    "alpaca": "alpaca",
}


def check(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        # Protected MCP endpoints commonly answer 401/405 to a bare GET; that
        # still proves DNS, TLS, tunnel routing, and the HTTP service are alive.
        if exc.code in {400, 401, 403, 405, 406}:
            return True, f"HTTP {exc.code} (reachable/protected)"
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check public MCP routes after a domain move")
    parser.add_argument("domain")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    domain = args.domain.strip().lower().rstrip(".")
    results = []
    for name, subdomain in SERVICES.items():
        url = f"https://{subdomain}.{domain}/mcp"
        ok, detail = check(url)
        results.append({"service": name, "url": url, "ok": ok, "detail": detail})
    if args.json:
        print(json.dumps({"domain": domain, "results": results}, indent=2))
    else:
        for item in results:
            mark = "PASS" if item["ok"] else "FAIL"
            print(f"[{mark}] {item['service']}: {item['url']} — {item['detail']}")
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
