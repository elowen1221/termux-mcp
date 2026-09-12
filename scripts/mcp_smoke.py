#!/usr/bin/env python3
"""Live-server smoke test for termux-mcp (REST + MCP Streamable HTTP).

Starts the real server (REST + MCP) on free loopback ports, then validates:

  1. REST GET /ping works without auth.
  2. REST protected endpoint (GET /env) rejects a missing Bearer token.
  3. MCP POST /mcp rejects a missing Bearer token.
  4. Authenticated MCP initialize -> tools/list -> tools/call succeeds.

This requires a live server, so it is intentionally separate from the
pytest unit tests. Run it on the device or a Linux host:

    python scripts/mcp_smoke.py

Exit code 0 = all checks passed.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("TERMUX_MCP_AUTH_TOKEN", "smoke-test-token-0123456789")

EXPECTED_TOOLS = [
    "run_command",
    "read_file",
    "write_file",
    "list_files",
    "make_directory",
    "get_location",
    "get_battery",
    "send_notification",
]

FAILURES = []


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def http_request(url, method="GET", body=None, headers=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def wait_for(url, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http_request(url)
            return True
        except Exception:
            time.sleep(0.3)
    return False


async def mcp_flow(mcp_url):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(
        mcp_url, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            check(
                "MCP tools/list exposes exactly the 8 curated tools",
                names == EXPECTED_TOOLS,
                f"got {names}",
            )
            res = await session.call_tool("run_command", {"cmd": "echo smoke-ok"})
            text = res.content[0].text
            check(
                "MCP tools/call run_command returns structured JSON",
                all(
                    f'"{k}"' in text
                    for k in ("stdout", "stderr", "exit_code", "truncated",
                              "risk_level", "snapshots")
                )
                and "smoke-ok" in text,
                text[:120],
            )


def main():
    rest_port = _free_port()
    mcp_port = _free_port()
    rest_url = f"http://127.0.0.1:{rest_port}"
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"

    env = dict(os.environ)
    env["TERMUX_MCP_AUTH_TOKEN"] = TOKEN
    env["TERMUX_MCP_HOST"] = "127.0.0.1"
    env["TERMUX_MCP_PORT"] = str(rest_port)
    env["TERMUX_MCP_MCP_HOST"] = "127.0.0.1"
    env["TERMUX_MCP_MCP_PORT"] = str(mcp_port)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [sys.executable, "-m", "termux_mcp"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_for(f"{rest_url}/ping"):
            print("FAIL: REST server did not come up")
            return 1

        # 1. REST /ping works without auth.
        status, body = http_request(f"{rest_url}/ping")
        check("REST GET /ping returns 200 without auth", status == 200, body[:80])

        # 2. REST protected endpoint rejects missing Bearer.
        status, _ = http_request(f"{rest_url}/env")
        check("REST GET /env rejects missing Bearer token", status == 401)

        # 3. MCP /mcp rejects missing Bearer.
        status, _ = http_request(mcp_url, method="POST", body={})
        check("MCP POST /mcp rejects missing Bearer token", status == 401)

        # 4. Authenticated MCP flow.
        asyncio.run(mcp_flow(mcp_url))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())