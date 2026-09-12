"""Tests for the MCP Streamable HTTP layer."""

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from termux_mcp.config import AUTH_TOKEN
from termux_mcp.mcp_server import _build_mcp_app

EXPECTED_TOOLS = [
    "run_command",
    "read_file",
    "write_file",
    "list_files",
    "make_directory",
    "get_location",
    "get_battery",
    "send_notification",
    "permissions_status",
    "inbox_list",
    "inbox_get",
    "inbox_ack",
    "inbox_status",
    "board_add",
    "board_list",
    "board_get",
    "board_update",
    "board_status",
    "mcp_install",
    "mcp_list",
    "mcp_search",
    "mcp_inspect",
    "mcp_health",
    "mcp_call",
    "mcp_remove",
    "run_steps",
]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def mcp_server():
    port = _free_port()
    app = _build_mcp_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(100):
        try:
            httpx.get(url, timeout=0.3)
            break
        except Exception:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def test_mcp_requires_auth(mcp_server):
    assert httpx.post(mcp_server, json={}).status_code == 401


def test_mcp_rejects_wrong_token(mcp_server):
    r = httpx.post(mcp_server, json={}, headers={"Authorization": "Bearer wrong-token-0000000000000000"})
    assert r.status_code == 401


def test_mcp_accepts_valid_token(mcp_server):
    r = httpx.post(mcp_server, json={}, headers={"Authorization": f"Bearer {AUTH_TOKEN}"})
    assert r.status_code != 401


def test_mcp_rejects_token_in_query_string(mcp_server):
    assert httpx.post(f"{mcp_server}?token={AUTH_TOKEN}", json={}).status_code == 401


def test_tools_list_and_call_smoke(mcp_server):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def run():
        async with streamablehttp_client(
            mcp_server, headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [t.name for t in tools.tools] == EXPECTED_TOOLS

                res = await session.call_tool("run_command", {"cmd": "echo hello"})
                assert res.isError is False
                text = res.content[0].text
                for key in ("stdout", "stderr", "exit_code", "truncated", "risk_level", "snapshots"):
                    assert f'"{key}"' in text
                assert "hello" in text

                batch = await session.call_tool("run_steps", {
                    "steps": [
                        {"tool": "run_command", "arguments": {"cmd": "echo one"}},
                        {"tool": "run_command", "arguments": {"cmd": "echo two"}},
                    ]
                })
                assert batch.isError is False
                batch_text = batch.content[0].text
                assert '"executed_steps": 2' in batch_text
                assert "one" in batch_text and "two" in batch_text

    asyncio.run(run())


def test_tools_call_dangerous_blocked(mcp_server):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def run():
        async with streamablehttp_client(
            mcp_server, headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("run_command", {"cmd": "rm -rf /"})
                text = res.content[0].text
                assert '"blocked": true' in text
                assert '"risk_level": "dangerous"' in text

    asyncio.run(run())


def test_tools_call_warning_confirmation_required(mcp_server):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def run():
        async with streamablehttp_client(
            mcp_server, headers={"Authorization": f"Bearer {AUTH_TOKEN}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("run_command", {"cmd": "rm -rf somefile"})
                text = res.content[0].text
                assert '"confirmation_required": true' in text
                assert '"risk_level": "warning"' in text

    asyncio.run(run())
