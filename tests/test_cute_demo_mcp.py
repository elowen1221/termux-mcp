"""End-to-end proof that the gateway can operate a third-party stdio MCP."""

import asyncio
import sys
from pathlib import Path

from termux_mcp import managed_mcp

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SERVER = REPO_ROOT / "examples" / "cute_demo_mcp.py"


def test_cute_demo_discovery_and_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_mcp, "REGISTRY_FILE", tmp_path / "managed.json")
    managed_mcp._save_registry({
        "cute-demo": {
            "name": "cute-demo",
            "source": "bundled-example",
            "transport": "stdio",
            "command": [sys.executable, str(DEMO_SERVER)],
            "cwd": str(REPO_ROOT),
            "runtime": "python",
            "installed_at": 0,
        }
    })

    async def exercise():
        discovered = await managed_mcp.inspect("cute-demo")
        assert [tool["name"] for tool in discovered["tools"]] == [
            "say_hello",
            "add_numbers",
            "mood_check",
        ]

        greeting = await managed_mcp.call(
            "cute-demo", "say_hello", {"name": "祁桉"}
        )
        greeting_text = greeting["content"][0]["text"]
        assert "你好，祁桉" in greeting_text
        assert "( Ꙭ)" in greeting_text

        addition = await managed_mcp.call(
            "cute-demo", "add_numbers", {"a": 20, "b": 22}
        )
        assert '"result": 42' in addition["content"][0]["text"]

    asyncio.run(exercise())
