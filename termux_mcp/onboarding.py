"""Friendly one-time onboarding for people who have never used Termux or MCP."""

import argparse
import sys
from collections.abc import Callable
from contextlib import ExitStack
from typing import TextIO

from . import config

CLIENTS = {"1": "chatgpt", "2": "claude", "3": "grok"}
PERMISSIONS = {"1": "standard", "2": "read-only", "3": "full"}
DISPLAY_NAMES = {"chatgpt": "ChatGPT", "claude": "Claude", "grok": "Grok"}


def _choice(prompt: str, mapping: dict[str, str], default: str, read: Callable[[str], str]) -> str:
    while True:
        value = read(prompt).strip().lower()
        if not value:
            return default
        if value in mapping:
            return mapping[value]
        if value in mapping.values():
            return value
        print("  没看懂这个选项，输入前面的数字就好啦 (｡•́︿•̀｡)")


def _yes_no(prompt: str, default: bool, read: Callable[[str], str]) -> bool:
    while True:
        value = read(prompt).strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "1", "是", "好", "要"}:
            return True
        if value in {"n", "no", "0", "否", "不", "不要"}:
            return False
        print("  输入 y 或 n 就可以啦。")


def _print_client_steps(client: str, url: str, output: TextIO) -> None:
    name = DISPLAY_NAMES[client]
    print("\n┌─ 最后一步：把手机接给 AI ─────────────────┐", file=output)
    print(f"│  ① 打开 {name} 的 MCP / Plugins / Connectors 设置", file=output)
    print("│  ② 新增一个 MCP Server", file=output)
    print("│  ③ 类型选 Streamable HTTP（有 HTTP 就选 HTTP）", file=output)
    print("│  ④ 把下面这一个地址粘进去", file=output)
    print("└──────────────────────────────────────────┘", file=output)
    print(f"\n{url}", file=output)
    print("\n不用把终端里的 Auth token 发给任何人。", file=output)
    print("客户端如果能直接完成 OAuth/授权，就按客户端提示继续；", file=output)
    print("如果它明确要求 Bearer token，再在你自己的手机上运行：termux-mcp token --show", file=output)


def run_setup(args: argparse.Namespace, start_callback: Callable[[argparse.Namespace], int], input_stream: TextIO | None = None, output: TextIO | None = None) -> int:
    """Explain the minimum concepts, save choices, start, and show next steps."""
    output = output or sys.stdout
    interactive = not args.non_interactive

    if config.SETUP_COMPLETE and not args.force:
        print("Termux-MCP 已经配置过啦 ( Ꙭ)", file=output)
        print("查看连接地址：termux-mcp url", file=output)
        print("重新走一遍新手向导：termux-mcp setup --force", file=output)
        return 0

    print("\n╭──────────────────────────────────────────╮", file=output)
    print("│            Termux-MCP 新手向导           │", file=output)
    print("│                  ( Ꙭ)                    │", file=output)
    print("│   不需要懂 Linux、端口或 MCP，跟着选就好   │", file=output)
    print("╰──────────────────────────────────────────╯", file=output)
    print("\n先说人话：它会在你的 Android 手机上开一个受保护的小入口，", file=output)
    print("让你选中的 AI 在你授权的范围里调用 Termux 能力。", file=output)
    print("默认会使用免费的公网隧道，所以不需要购买域名。", file=output)

    with ExitStack() as stack:
        if interactive and input_stream is None:
            try:
                input_stream = stack.enter_context(open("/dev/tty", "r", encoding="utf-8"))
            except OSError:
                input_stream = sys.stdin

        def read(prompt: str) -> str:
            print(prompt, end="", file=output, flush=True)
            return input_stream.readline() if input_stream is not None else ""

        client = args.client
        permissions = args.permissions
        no_tunnel = args.no_tunnel

        if interactive:
            print("\n[1/3] 你主要准备在哪个客户端里用？", file=output)
            print("  1. ChatGPT（默认）\n  2. Claude\n  3. Grok", file=output)
            client = client or _choice("输入数字 [1]：", CLIENTS, "chatgpt", read)

            print("\n[2/3] AI 可以在手机里做到什么？", file=output)
            print("  1. 日常模式（推荐）— 常用操作可直接做，危险操作仍会拦截", file=output)
            print("  2. 只读模式 — 适合第一次试用，只允许查看类操作", file=output)
            print("  3. 完全控制 — 权限最大，确认自己需要时再选", file=output)
            permissions = permissions or _choice("输入数字 [1]：", PERMISSIONS, "standard", read)

            if not args.no_tunnel and args.tunnel == "auto":
                print("\n[3/3] 要从外面的 AI 客户端连接这台手机吗？", file=output)
                print("  推荐选 y。会自动尝试免费隧道，不需要域名，也不用先学 Cloudflare。", file=output)
                use_public = _yes_no("使用免费公网连接？[Y/n]：", True, read)
                no_tunnel = not use_public
            else:
                print("\n[3/3] 公网连接方式已经由启动参数指定，跳过选择。", file=output)
        else:
            client = client or "chatgpt"
            permissions = permissions or "standard"

    config.ensure_token()
    config.save_user_preferences(client, permissions)
    display_name = DISPLAY_NAMES[client]
    print("\n正在自动检查和启动，不需要再输入命令……", file=output)
    print(f"  ✓ 客户端：{display_name}", file=output)
    print(f"  ✓ 权限：{permissions}", file=output)
    print("  ✓ 随机访问密钥已安全保存在本机", file=output)

    start_args = argparse.Namespace(no_tunnel=no_tunnel, tunnel=args.tunnel)
    rc = start_callback(start_args)
    if rc:
        print("\n连接没有启动成功 (つ﹏<。)", file=output)
        print("先运行：termux-mcp doctor", file=output)
        print("它会告诉你卡在哪一步；把输出发给维护者也可以。", file=output)
        return rc

    public_url = config.get_public_url()
    url = public_url.rstrip("/") + "/mcp" if public_url and not no_tunnel else f"http://127.0.0.1:{config.MCP_PORT}/mcp"

    print("\n╭──────────────────────────────────────────╮", file=output)
    print("│             手机这边已经完成 ✓           │", file=output)
    print("╰──────────────────────────────────────────╯", file=output)
    if no_tunnel:
        print("\n你选择了只在手机本机使用，所以当前地址是本地地址。", file=output)
        print(f"{url}", file=output)
        print("以后想让外部 AI 连接：termux-mcp restart --tunnel auto", file=output)
    else:
        _print_client_steps(client, url, output)
        print("\n免费地址小提醒：只要隧道还活着，普通 restart/start 都会尽量保留它。", file=output)
        print("手机重启或免费隧道真正断开后，地址才可能变化；用 termux-mcp url 随时查看。", file=output)
    print("\n以后常用的其实只有两个命令：", file=output)
    print("  termux-mcp status   # 看它还活着没有", file=output)
    print("  termux-mcp url      # 看现在该填哪个地址", file=output)
    return 0
