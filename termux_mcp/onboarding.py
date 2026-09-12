"""Cute, beginner-first onboarding without hiding advanced connection choices."""
import argparse, re, sys
from collections.abc import Callable
from contextlib import ExitStack
from typing import TextIO
from urllib.parse import urlparse
from . import config

CLIENTS={"1":"chatgpt","2":"claude","3":"grok"}; PERMISSIONS={"1":"standard","2":"read-only","3":"full"}
CONNECTIONS={"1":"free","2":"domain","3":"external","4":"local"}
DISPLAY_NAMES={"chatgpt":"ChatGPT","claude":"Claude","grok":"Grok"}

def _choice(prompt,mapping,default,read):
    while True:
        value=read(prompt).strip().lower()
        if not value:return default
        if value in mapping:return mapping[value]
        if value in mapping.values():return value
        print("  没看懂这个选项，输入前面的数字就好啦 (｡•́︿•̀｡)")

def _hostname(value):
    host=value.strip().lower().rstrip(".")
    if re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",host):return host
    raise ValueError

def _domain(read,output):
    while True:
        raw=read("你的域名：").strip()
        try:return _hostname(raw)
        except ValueError:
            print("  这个看起来不像域名 (｡•́︿•̀｡)",file=output); print("  例如：example.com（不要带 https:// 或 /mcp）",file=output)

def _subdomain(domain,read,output):
    while True:
        label=read("子域名 [termux]：").strip().lower() or "termux"
        try:return _hostname(f"{label}.{domain}")
        except ValueError:print("  子域名有点奇怪，试试 termux、mcp 或 phone。",file=output)

def _external_url(read,output):
    while True:
        raw=read("现成的 HTTPS 地址：").strip().rstrip("/")
        p=urlparse(raw)
        if p.scheme=="https" and p.hostname and not p.query and not p.fragment:return raw[:-4] if raw.endswith("/mcp") else raw
        print("  请填完整 HTTPS 地址，例如 https://mcp.example.com",file=output)

def _print_client_steps(client,url,output):
    name=DISPLAY_NAMES[client]
    print("\n┌─ 最后一步：把手机接给 AI ─────────────────┐",file=output)
    print(f"│  ① 打开 {name} 的 MCP / Plugins / Connectors 设置",file=output)
    print("│  ② 新增一个 MCP Server",file=output); print("│  ③ 类型选 Streamable HTTP（有 HTTP 就选 HTTP）",file=output)
    print("│  ④ 把下面这个地址粘进去",file=output); print("└──────────────────────────────────────────┘",file=output)
    print(f"\n{url}\n",file=output); print("不用把终端里的 Auth token 发给任何人。",file=output)

def run_setup(args,start_callback,input_stream=None,output=None):
    output=output or sys.stdout; interactive=not args.non_interactive
    if config.SETUP_COMPLETE and not args.force:
        print("Termux-MCP 已经配置过啦 ( Ꙭ)\n查看连接地址：termux-mcp url\n重新走向导：termux-mcp setup --force",file=output); return 0
    print("\n╭──────────────────────────────────────────╮\n│            Termux-MCP 新手向导           │\n│                  ( Ꙭ)                    │\n│     不懂 Linux / MCP 也没关系，跟我走     │\n╰──────────────────────────────────────────╯",file=output)
    print("\n不知道选什么？一路按 Enter 就可以。",file=output)
    print("\n开始前先送你一张小抄：安装完成后运行 termux-mcp guide",file=output)
    print("它会显示最常用的 5 个命令，而且排好了版，方便直接截图保存。",file=output)
    print("⚠ 不要把 termux-mcp token --show 的结果截给别人。",file=output)
    with ExitStack() as stack:
        if interactive and input_stream is None:
            try:input_stream=stack.enter_context(open("/dev/tty","r",encoding="utf-8"))
            except OSError:input_stream=sys.stdin
        def read(prompt):
            print(prompt,end="",file=output,flush=True); return input_stream.readline() if input_stream is not None else ""
        client=args.client; permissions=args.permissions; mode="local" if args.no_tunnel else "free"; value=""; desired_url=""
        if interactive:
            print("\n( Ꙭ) 第一件事——你想把谁接进手机里？\n  1. ChatGPT  ← 推荐\n  2. Claude\n  3. Grok",file=output)
            client=client or _choice("你的选择 [1]：",CLIENTS,"chatgpt",read)
            print("\n( Ꙭ) 接下来，给 AI 一点活动空间。\n  1. 🌿 日常活动  ← 推荐\n  2. 🌱 只看看\n  3. 🌳 完全开放",file=output)
            permissions=permissions or _choice("你的选择 [1]：",PERMISSIONS,"standard",read)
            if not args.no_tunnel and args.tunnel=="auto":
                print("\n( Ꙭ) 最后，AI 要怎么找到这台手机？",file=output)
                print("  1. 免费地址  ← 推荐\n     不用域名，我自动帮你开",file=output)
                print("  2. 我有自己的域名\n     例如 example.com，可以准备固定地址",file=output)
                print("  3. 我已经有现成公网地址\n     VPS / 反代 / 其他入口都可以",file=output)
                print("  4. 暂时只在手机本机使用",file=output)
                mode=_choice("你的选择 [1]：",CONNECTIONS,"free",read)
                if mode=="domain":
                    print("\n好，把你自己的域名告诉我。这里只填主域名，不带 https://。",file=output)
                    domain=_domain(read,output); print(f"\n想放在哪个子域名？直接 Enter 会用 termux.{domain}",file=output)
                    host=_subdomain(domain,read,output); value=host; desired_url=f"https://{host}"
                    print(f"\n✓ 记住啦：{desired_url}/mcp",file=output)
                    print("  这一步只保存你的选择，不会擅自修改 DNS。",file=output)
                    print("  Named Tunnel / DNS 自动配置会在后续向导里单独确认。",file=output)
                elif mode=="external":
                    print("\n把你已经配置好的公网入口给我，我不会改它。",file=output); desired_url=_external_url(read,output); value=desired_url
                elif mode=="local": args.no_tunnel=True
        else:
            client=client or "chatgpt"; permissions=permissions or "standard"
    config.ensure_token(); config.save_user_preferences(client,permissions); config.save_connection_preference(mode,value)
    display=DISPLAY_NAMES[client]
    print(f"\n正在收拾小窝…… ( Ꙭ)و\n  ✓ 客户端：{display}\n  ✓ 权限：{permissions}\n  ✓ 连接路线：{mode}\n  ✓ 小钥匙已经安全保存在本机",file=output)
    # Domain/external routes are not anonymous tunnels. Start local MCP only;
    # never pretend DNS/tunnel configuration succeeded merely because a host was typed.
    no_tunnel = args.no_tunnel or mode in {"domain","external","local"}
    rc=start_callback(argparse.Namespace(no_tunnel=no_tunnel,tunnel=args.tunnel))
    if rc:
        print("\n门卡住了 (｡•́︿•̀｡)\n你的配置没有丢。先运行：termux-mcp doctor",file=output); return rc
    runtime=config.get_public_url()
    if mode=="free" and runtime: url=runtime.rstrip("/")+"/mcp"
    elif mode in {"domain","external"}: url=desired_url.rstrip("/")+"/mcp"
    else:url=f"http://127.0.0.1:{config.MCP_PORT}/mcp"
    print("\n╭──────────────────────────────────────────╮\n│              ૮₍ ˶ᵔ ᵕ ᵔ˶ ₎ა               │\n│             手机这边完成啦 ✓              │\n╰──────────────────────────────────────────╯",file=output)
    if mode=="domain":
        print(f"\n你的目标固定地址：\n{url}\n\n注意：现在只保存了域名，还没有宣称它已经能访问。",file=output)
        print("下一步需要配置 Cloudflare Named Tunnel / DNS；这一步会单独确认后再改。",file=output)
    elif mode=="external":
        print("\n本机 MCP 已启动；你提供的公网入口不会被 Termux-MCP 擅自修改。",file=output); _print_client_steps(client,url,output)
    elif mode=="local": print(f"\n当前只在手机本机使用：\n{url}",file=output)
    else:_print_client_steps(client,url,output); print("\n免费地址在隧道存活期间会尽量保留；手机重启或隧道真正断开后可能变化。",file=output)
    print("\n不知道下一步或想保存常用命令：\n  termux-mcp guide   # 打开可截图的新手小抄",file=output)
    print("\n平时最常用：\n  termux-mcp status  # 看状态\n  termux-mcp url     # 看连接地址",file=output); return 0
