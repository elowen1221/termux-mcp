"""Friendly one-time onboarding for non-technical Termux users."""

import argparse
import sys
from collections.abc import Callable
from contextlib import ExitStack
from typing import TextIO

from . import config

CLIENTS = {"1": "chatgpt", "2": "claude", "3": "grok"}
PERMISSIONS = {"1": "standard", "2": "full", "3": "read-only"}
DISPLAY_NAMES = {"chatgpt": "ChatGPT", "claude": "Claude", "grok": "Grok"}


def _choice(
    prompt: str,
    mapping: dict[str, str],
    default: str,
    read: Callable[[str], str],
) -> str:
    while True:
        value = read(prompt).strip().lower()
        if not value:
            return default
        if value in mapping:
            return mapping[value]
        if value in mapping.values():
            return value
        print("  没看懂这个选项，再试一次吧 (｡•́︿•̀｡)")


def run_setup(
    args: argparse.Namespace,
    start_callback: Callable[[argparse.Namespace], int],
    input_stream: TextIO | None = None,
    output: TextIO | None = None,
) -> int:
    """Save first-run choices, start the gateway, and present one URL."""
    output = output or sys.stdout
    interactive = not args.non_interactive

    if config.SETUP_COMPLETE and not args.force:
        print("Termux-MCP 已经准备好啦 ( Ꙭ)", file=output)
        print("需要重新选择时运行：termux-mcp setup --force", file=output)
        return 0

    print(file=output)
    print("╭──────────────────────────────────╮", file=output)
    print("│          Termux-MCP              │", file=output)
    print("│            ( Ꙭ)                  │", file=output)
    print("│    正在给 AI 准备一扇小门……       │", file=output)
    print("╰──────────────────────────────────╯", file=output)

    with ExitStack() as stack:
        if interactive and input_stream is None:
            try:
                input_stream = stack.enter_context(
                    open("/dev/tty", "r", encoding="utf-8")
                )
            except OSError:
                input_stream = sys.stdin

        def read(prompt: str) -> str:
            print(prompt, end="", file=output, flush=True)
            line = input_stream.readline() if input_stream is not None else ""
            return line

        client = args.client
        permissions = args.permissions
        if interactive:
            print("\n( Ꙭ) 你准备把哪位 AI 接进手机？", file=output)
            print("  1. ChatGPT（默认）\n  2. Claude\n  3. Grok", file=output)
            client = client or _choice("请选择 [1]：", CLIENTS, "chatgpt", read)
            print("\n( Ꙭ) 要给它多大的活动空间？", file=output)
            print("  1. 🌿 日常使用（默认）", file=output)
            print("  2. 🌳 完全控制", file=output)
            print("  3. 🌱 只读模式", file=output)
            permissions = permissions or _choice(
                "请选择 [1]：", PERMISSIONS, "standard", read
            )
        else:
            client = client or "chatgpt"
            permissions = permissions or "standard"

    config.ensure_token()
    config.save_user_preferences(client, permissions)
    print("\n  ✓ 已记住你的权限选择", file=output)
    print("  ✓ 已准备统一 MCP 入口", file=output)
    display_name = DISPLAY_NAMES[client]
    print(f"  ✓ 已记住首选客户端：{display_name}", file=output)
    print("\n正在打开连接通道…… ( Ꙭ)و", file=output)

    start_args = argparse.Namespace(no_tunnel=args.no_tunnel, tunnel=args.tunnel)
    rc = start_callback(start_args)
    if rc:
        print("\n连接通道打了个喷嚏 (つ﹏<。)", file=output)
        print("运行 termux-mcp doctor 查看原因。", file=output)
        return rc

    public_url = config.get_public_url()
    url = (
        public_url.rstrip("/") + "/mcp"
        if public_url and not args.no_tunnel
        else f"http://127.0.0.1:{config.MCP_PORT}/mcp"
    )
    print("\n╭──────────────────────────────────╮", file=output)
    print("│  好耶，已经准备好了！૮₍ ˃ ⤙ ˂ ₎ა │", file=output)
    print("╰──────────────────────────────────╯", file=output)
    print(f"\n把这个地址交给 {display_name}：\n{url}", file=output)
    print("\n接下来直接在对话框里告诉 AI 要做什么就好啦～", file=output)
    return 0
