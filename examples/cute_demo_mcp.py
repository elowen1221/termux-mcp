"""A tiny stdio MCP server used to verify Termux-MCP's managed gateway.

Run directly with:
    python examples/cute_demo_mcp.py

It is intentionally dependency-light: the main project already installs the
official ``mcp`` Python SDK.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "cute-demo-mcp",
    instructions="A friendly demo server for greetings, addition, and mood checks.",
)


@mcp.tool()
def say_hello(name: str = "朋友") -> dict:
    """Return a friendly greeting for someone."""
    clean_name = name.strip() or "朋友"
    return {
        "message": f"你好，{clean_name}！Termux-MCP 在这里 ( Ꙭ)",
        "server": "cute-demo-mcp",
    }


@mcp.tool()
def add_numbers(a: float, b: float) -> dict:
    """Add two numbers and return the exact numeric result."""
    return {"a": a, "b": b, "result": a + b}


@mcp.tool()
def mood_check(message: str) -> dict:
    """Give a tiny, deterministic mood response for a message."""
    text = message.strip()
    if not text:
        mood = "quiet"
        reply = "安静地待一会儿也很好呀。"
    elif any(mark in text for mark in ("开心", "好耶", "love", "happy")):
        mood = "happy"
        reply = "检测到开心信号！૮₍ ˃ ⤙ ˂ ₎ა"
    else:
        mood = "curious"
        reply = "收到啦，我会认真听着的 ( Ꙭ)"
    return {"mood": mood, "reply": reply}


if __name__ == "__main__":
    mcp.run(transport="stdio")
