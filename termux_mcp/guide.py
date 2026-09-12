"""A screenshot-friendly pocket guide for first-time Termux-MCP users."""
import sys
from typing import TextIO
from . import config, process

COMMANDS = (
    ("termux-mcp status", "看看 MCP 和连接还活着没有"),
    ("termux-mcp url", "看看现在应该填给 AI 的地址"),
    ("termux-mcp guide", "忘记下一步时，再叫出这张小抄"),
    ("termux-mcp doctor", "出问题时自动检查哪里卡住了"),
    ("termux-mcp restart", "只重启 MCP；能保留的免费地址会尽量保留"),
)

def _connection_state():
    mode=config.CONNECTION_MODE if config.CONNECTION_MODE in {"free","domain","external","local"} else "free"
    return mode, config.CONNECTION_VALUE

def run_guide(output: TextIO | None=None) -> int:
    output=output or sys.stdout
    print("\n╭──────────────────────────────────────────╮",file=output)
    print("│            ( Ꙭ) 新手随身小抄            │",file=output)
    print("│       这一页很适合现在直接截个图保存       │",file=output)
    print("╰──────────────────────────────────────────╯",file=output)
    print("\n先记住这 5 个就够啦：",file=output)
    for command,desc in COMMANDS: print(f"\n  {command}\n    {desc}",file=output)
    print("\n⚠ 小钥匙不要截图分享：",file=output)
    print("  termux-mcp token --show",file=output)
    print("  只有客户端明确要求 Bearer token 时，才在自己的手机上查看。",file=output)
    print("\n──────────── 你现在到哪啦 ────────────",file=output)
    mode,value=_connection_state(); running=process.is_running(); runtime=config.get_public_url()
    print(f"  MCP：{'✓ 正在运行' if running else '○ 还没运行'}",file=output)
    if mode=="free":
        if runtime: print(f"  免费连接：✓ {runtime.rstrip('/')}/mcp",file=output)
        else: print("  免费连接：○ 还没有可用地址",file=output)
        print("\n下一步："+("把上面的 /mcp 地址添加到你的 AI 客户端。" if runtime else "运行 termux-mcp start，让我帮你打开免费连接。"),file=output)
    elif mode=="domain":
        print(f"  自有域名：{value or '还没填写'}",file=output)
        print("\n下一步：运行 termux-mcp domain guide",file=output)
        print("它会检查 cloudflared / 登录 / Named Tunnel / 配置文件，并且每次只告诉你下一步。",file=output)
        print("在确认 DNS 改动前，Termux-MCP 不会擅自修改你的域名。",file=output)
    elif mode=="external":
        url=(value.rstrip('/')+'/mcp') if value else '还没填写'
        print(f"  现成公网入口：{url}",file=output); print("\n下一步：确认你的反代/入口已经转发到本机 MCP，然后把地址添加给 AI。",file=output)
    else:
        print("  连接方式：只在手机本机使用",file=output); print("\n下一步：如果以后想让外面的 AI 连接，重新运行 termux-mcp setup --force。",file=output)
    print("\n出问题别重装。先跑 termux-mcp doctor，再把结果截图给帮你的人。",file=output)
    return 0
