"""termux-mcp command-line interface.

Commands:
  termux-mcp                          Run the server in the foreground (default).
  termux-mcp start [--tunnel MODE]    Start server + optional public tunnel.
  termux-mcp stop                     Stop the running server (and tunnel).
  termux-mcp restart [--tunnel MODE]  Restart the server (tunnel kept by default).
  termux-mcp status                   Show server / tunnel / auth status.
  termux-mcp logs [-n N]              Show recent server logs.
  termux-mcp doctor [--json]          Run human or machine-readable self-checks.
  termux-mcp token [--show] [--rotate]  Manage the auth token.
  termux-mcp setup                    Run the friendly first-time connection flow.
  termux-mcp permissions              Show or change the AI permission mode.

`start` is the one-command experience: it ensures an auth token exists,
starts the server, waits for REST + MCP health, starts the selected tunnel,
verifies the public URL, and prints the final MCP URL.

`restart` is server-only by default: the running tunnel, its PID and the
verified public URL are preserved so ChatGPT's saved MCP URL stays valid
even though anonymous tunnel hostnames change between tunnel rebuilds.
Pass --tunnel <mode> to rebuild the tunnel, or --no-tunnel to stop it.
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from packaging.version import InvalidVersion, Version

from . import __version__
from . import process
from . import config as config_mod
from . import tunnel as tunnel_mod
from .config import (
    AUTH_TOKEN,
    MCP_ENABLED,
    MCP_HOST,
    MCP_PORT,
    PORT,
    WORKSPACE_ROOT,
    clear_public_url,
    ensure_token,
    get_public_url,
    get_last_public_url,
    public_url_source,
    rotate_token,
    set_public_url,
    token_configured,
)

TUNNEL_CHOICES = ["auto", "relay", "pinggy", "cloudflare", "localhost-run", "none"]


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="termux-mcp",
        description="Termux MCP server — REST API + MCP Streamable HTTP + tunnel launcher.",
    )
    parser.add_argument("--version", action="version", version=f"termux-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Start the server (and optionally a tunnel)")
    p_start.add_argument(
        "--tunnel", default="auto", choices=TUNNEL_CHOICES,
        help="Tunnel provider (default: auto)",
    )
    p_start.add_argument(
        "--no-tunnel", action="store_true",
        help="Start the server without any public tunnel",
    )
    lan_group = p_start.add_mutually_exclusive_group()
    lan_group.add_argument("--lan", action="store_true", help="Persist LAN access using the current Wi-Fi IPv4 address")
    lan_group.add_argument("--local-only", action="store_true", help="Persist localhost-only access (disable LAN mode)")

    sub.add_parser("stop", help="Stop the running server and tunnel")

    p_restart = sub.add_parser("restart", help="Restart the server (tunnel kept by default)")
    p_restart.add_argument(
        "--tunnel", default=None, choices=TUNNEL_CHOICES,
        help="Rebuild the tunnel with this provider (default: keep the running tunnel)",
    )
    p_restart.add_argument("--named-tunnel", default=None, help="Start/keep a Cloudflare Named Tunnel by name")
    p_restart.add_argument("--named-config", default="~/.cloudflared/config.yml", help="Named Tunnel config path")
    p_restart.add_argument(
        "--no-tunnel", action="store_true",
        help="Stop the tunnel and restart the server without one",
    )

    sub.add_parser("status", help="Show server / tunnel / auth status")
    p_components = sub.add_parser("components", help="Inspect the local component registry")
    components_sub = p_components.add_subparsers(dest="components_action", required=True)
    components_sub.add_parser("list", help="List registered component IDs")
    p_ci = components_sub.add_parser("inspect", help="Inspect one registered component")
    p_ci.add_argument("component")
    components_sub.add_parser("reconcile", help="Compare desired and actual component state")
    components_sub.add_parser("topology", help="Show component topology and desired/actual state")
    p_cr = components_sub.add_parser("recover-plan", help="Show the registered recovery policy without executing it")
    p_cr.add_argument("component")
    p_cre = components_sub.add_parser("recover", help="Execute a registered recovery policy")
    p_cre.add_argument("component")
    p_apps = sub.add_parser("apps", help="Inspect registered Android app capabilities")
    apps_sub = p_apps.add_subparsers(dest="apps_action", required=True)
    p_al = apps_sub.add_parser("list", help="List registered Android apps")
    p_al.add_argument("--category", default=None)
    p_as = apps_sub.add_parser("show", help="Show one app's package, capabilities, and permission policy")
    p_as.add_argument("app")
    p_ad = apps_sub.add_parser("doctor", help="Check Android bridge and installation readiness for one app")
    p_ad.add_argument("app")
    p_aa = apps_sub.add_parser("authorize", help="Explain whether a registered app action is allowed")
    p_aa.add_argument("app"); p_aa.add_argument("action")
    p_ax = apps_sub.add_parser("launch", help="Launch a registered Android app through its declared driver")
    p_ax.add_argument("app")
    p_ab = apps_sub.add_parser("browse", help="Read the visible semantic UI of a registered app")
    p_ab.add_argument("app"); p_ab.add_argument("--depth", type=int, default=8)
    p_act = apps_sub.add_parser("act", help="Perform a governed semantic action in the foreground app")
    p_act.add_argument("app"); p_act.add_argument("action"); p_act.add_argument("--text", default=""); p_act.add_argument("--view-id", default=""); p_act.add_argument("--desc", default=""); p_act.add_argument("--index", type=int, default=0)
    sub.add_parser("url", help="Show the current public MCP URL and whether it is being preserved")
    sub.add_parser("guide", help="Show a beginner cheat sheet and the next connection step")

    p_logs = sub.add_parser("logs", help="Show recent server logs")
    p_logs.add_argument("-n", type=int, default=50, help="Number of lines (default 50)")

    p_doctor = sub.add_parser("doctor", help="Run self-checks")
    p_doctor.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit a machine-readable diagnostic report",
    )

    p_update = sub.add_parser("update", help="Check and apply stable Termux-MCP releases")
    update_sub = p_update.add_subparsers(dest="update_action", required=True)
    p_update_check = update_sub.add_parser("check", help="Check origin for a newer stable release without changing anything")
    p_update_check.add_argument("--json", action="store_true", dest="json_output")

    p_token = sub.add_parser("token", help="Manage the auth token")
    p_token.add_argument("--show", action="store_true", help="Print the full token")
    p_token.add_argument("--rotate", action="store_true", help="Generate a new token")

    p_setup = sub.add_parser("setup", help="First-time guided setup")
    p_setup.add_argument("--client", choices=["chatgpt", "claude", "grok"])
    p_setup.add_argument(
        "--permissions", choices=["read-only", "standard", "full"]
    )
    p_setup.add_argument("--tunnel", default="auto", choices=TUNNEL_CHOICES)
    p_setup.add_argument("--no-tunnel", action="store_true")
    p_setup.add_argument("--non-interactive", action="store_true")
    p_setup.add_argument("--force", action="store_true")

    p_permissions = sub.add_parser("permissions", help="Show or change permissions")
    permissions_sub = p_permissions.add_subparsers(dest="permissions_action")
    p_permissions_set = permissions_sub.add_parser("set", help="Set permission mode")
    p_permissions_set.add_argument("mode", choices=["read-only", "standard", "full"])

    p_domain = sub.add_parser("domain", help="Manage Cloudflare named-tunnel routes")
    domain_sub = p_domain.add_subparsers(dest="domain_command", required=True)
    p_domain_guide = domain_sub.add_parser("guide", help="Show the safe next step for an own-domain setup")
    p_domain_guide.add_argument("hostname", nargs="?", default=None)
    p_domain_list = domain_sub.add_parser("list", help="List configured ingress routes")
    p_domain_list.add_argument("--config", default=None)
    p_domain_add = domain_sub.add_parser("add", help="Add and validate an ingress route")
    p_domain_add.add_argument("hostname")
    p_domain_add.add_argument("--port", type=int, required=True)
    p_domain_add.add_argument("--tunnel", required=True)
    p_domain_add.add_argument("--config", default=None)
    p_domain_add.add_argument(
        "--no-dns", action="store_true",
        help="Update ingress only; do not create the Cloudflare DNS route",
    )
    p_domain_plan = domain_sub.add_parser(
        "plan", help="Preview moving all ingress hosts to a new base domain"
    )
    p_domain_plan.add_argument("new_domain")
    p_domain_plan.add_argument("--from-domain", default=None)
    p_domain_plan.add_argument("--config", default=None)
    p_domain_migrate = domain_sub.add_parser(
        "migrate", help="Move ingress hosts to a new base domain safely"
    )
    p_domain_migrate.add_argument("new_domain")
    p_domain_migrate.add_argument("--from-domain", default=None)
    p_domain_migrate.add_argument("--tunnel", required=True)
    p_domain_migrate.add_argument("--config", default=None)
    p_domain_migrate.add_argument(
        "--no-dns", action="store_true",
        help="Rewrite and validate ingress only; do not create new DNS routes",
    )

    return parser.parse_args(argv)


# ── Commands ─────────────────────────────────────────────────────────────────

def _reuse_runtime_tunnel(choice: str, source: str, url: str, tunnel_running: bool) -> bool:
    """True when default start can safely keep the existing free URL."""
    return choice == "auto" and tunnel_running and source == "runtime" and bool(url)

def _select_lan_ipv4(ifconfig_text: str) -> str:
    """Best-effort Android LAN IPv4 discovery, preferring Wi-Fi/AP over VPN/mobile."""
    import ipaddress
    import re
    found = []
    iface = ""
    for line in ifconfig_text.splitlines():
        if line and not line[0].isspace() and ":" in line:
            iface = line.split(":", 1)[0]
        match = re.search(r"\binet (?:addr:)?(\d+(?:\.\d+){3})", line)
        if not match or not iface:
            continue
        ip = match.group(1)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not addr.is_private or addr.is_loopback:
            continue
        if iface.startswith(("tun", "ccmni", "rmnet", "lo")):
            continue
        rank = 0 if iface.startswith(("wlan", "ap")) else 1
        found.append((rank, iface, ip))
    found.sort()
    return found[0][2] if found else ""


def _detect_lan_ipv4() -> str:
    """Read Android interfaces and select a reachable LAN address."""
    import subprocess
    try:
        proc = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return _select_lan_ipv4(proc.stdout)


def cmd_start(args: argparse.Namespace) -> int:
    # Reject duplicate instances before mutating persistent LAN configuration.
    if process.is_running():
        print(f"termux-mcp is already running (pid {process.read_pid()}). Use termux-mcp restart to change running mode.")
        return 1

    # Load auth before starting; health checks need the configured token.
    token = ensure_token()
    print(f"Auth token: configured (length {len(token)})")

    # LAN exposure is persistent by design; ordinary restarts inherit it.
    if getattr(args, "lan", False):
        lan_ip = _detect_lan_ipv4()
        if not lan_ip:
            print("LAN mode not enabled: could not detect a non-loopback IPv4 address.")
            return 1
        config_mod.save_lan_mode(lan_ip)
        print(f"LAN mode saved: http://{lan_ip}:{MCP_PORT}/mcp")
    elif getattr(args, "local_only", False):
        config_mod.save_lan_mode("")
        print("Local-only mode saved.")

    # C. Start the server.
    pid = process.start_server()
    print(f"Server started (pid {pid})")

    # D. Wait for REST + MCP health.
    rest_ok = process.wait_http(PORT)
    mcp_ok, mcp_detail = (process.wait_mcp_initialize(MCP_PORT, token)
                          if MCP_ENABLED else (True, "disabled"))
    print(f"REST http://127.0.0.1:{PORT}: {'OK' if rest_ok else 'NOT RESPONDING'}")
    if MCP_ENABLED:
        print(f"MCP  http://127.0.0.1:{MCP_PORT}/mcp: {'OK' if mcp_ok else 'NOT RESPONDING'}")
        print(f"MCP initialize: {'OK' if mcp_ok else 'FAIL'} — {mcp_detail}")
    if not rest_ok or not mcp_ok:
        print("Server did not become healthy. Check 'termux-mcp logs'.")
        if process.is_running():
            process.stop_server()
        return 1

    # E/F/G/H. Tunnel. Anonymous/free tunnel hostnames are ephemeral, so the
    # default auto path must reuse a still-running tunnel instead of creating
    # a fresh hostname after a server crash/restart. Explicit --tunnel X still
    # means "rebuild with X".
    choice = "none" if args.no_tunnel else args.tunnel
    result = None
    mcp_url = ""
    previous_url = get_public_url()
    previous_source = public_url_source()
    previous_runtime_url = previous_url if previous_source == "runtime" else get_last_public_url()
    reuse_tunnel = _reuse_runtime_tunnel(
        choice, previous_source, previous_url, process.tunnel_is_running()
    )
    if choice != "none" and reuse_tunnel:
        mcp_url = previous_url.rstrip("/") + "/mcp"
        print(f"Tunnel kept (pid {process.read_tunnel_pid()}): {mcp_url}")
        if tunnel_mod.verify_url(previous_url):
            print("Public endpoint: reachable — existing free URL preserved")
        else:
            print("WARNING: preserved tunnel is still starting; URL was not rebuilt.")
    elif choice != "none":
        result = tunnel_mod.start_tunnel(MCP_PORT, choice)
        if result.url:
            mcp_url = result.url.rstrip("/") + "/mcp"
            print(f"Tunnel ({result.provider}): {mcp_url}")
            if result.process and result.process.pid:
                process.write_tunnel_pid(result.process.pid)
            set_public_url(result.url)
            if (previous_runtime_url
                    and previous_runtime_url.rstrip("/") != result.url.rstrip("/")):
                print("NOTICE: free tunnel URL changed because the old tunnel was no longer running.")
                print(f"Previous MCP URL: {previous_runtime_url.rstrip('/')}/mcp")
                print("Update the saved MCP URL in your client once; future server-only restarts keep this tunnel.")
            if tunnel_mod.verify_url(result.url):
                print("Public endpoint: reachable")
            else:
                print("WARNING: public endpoint not reachable yet — check network/VPN.")
        else:
            print(f"Tunnel failed: {result.error}")
            print("The server is still running locally — use 'termux-mcp start --no-tunnel'.")

    # I. Next steps.
    print("\nNext steps:")
    print(f"  REST API:   http://127.0.0.1:{PORT}")
    print(f"  MCP local:  http://127.0.0.1:{MCP_PORT}/mcp")
    if choice != "none" and mcp_url:
        print(f"  MCP public: {mcp_url}")
    print("  Status:     termux-mcp status")
    print("  Logs:       termux-mcp logs")
    print("  Stop:       termux-mcp stop")
    return 0


def cmd_stop() -> int:
    if process.tunnel_is_running():
        pid = process.read_tunnel_pid()
        process.kill_pid(pid)
        process.clear_tunnel_pid()
        print(f"Tunnel stopped (pid {pid})")
    else:
        # Clean up a stale tunnel.pid if present.
        process.clear_tunnel_pid()
    clear_public_url()
    if process.is_running():
        pid = process.read_pid()
        if not process.stop_server():
            print(f"ERROR: server pid {pid} did not stop.")
            return 1
        print(f"Server stopped (pid {pid})")
    else:
        process.clear_pid()
        print("Server is not running.")
    return 0


def _restart_tunnel_action(args: argparse.Namespace) -> str:
    """Decide how restart handles the tunnel: keep | rebuild | stop.

    Default is "keep" (server-only restart): the running tunnel and its
    verified public URL are preserved so ChatGPT's saved MCP URL stays
    valid. Explicit --tunnel <mode> rebuilds the tunnel; --no-tunnel
    stops it. `restart --tunnel auto` keeps the old "stop everything and
    rebuild" behavior.
    """
    if args.no_tunnel:
        return "stop"
    if args.tunnel is not None:
        return "rebuild"
    return "keep"


def cmd_restart(args: argparse.Namespace) -> int:
    action = _restart_tunnel_action(args)
    named_tunnel = getattr(args, "named_tunnel", None)
    named_config = os.path.expanduser(getattr(args, "named_config", "~/.cloudflared/config.yml"))
    if named_tunnel:
        pid = process.start_named_cloudflare_tunnel(named_config, named_tunnel)
        if not pid:
            print(f"ERROR: could not start named tunnel {named_tunnel}.")
            return 1
        print(f"Named tunnel ready (pid {pid}): {named_tunnel}")

    # Self-restart through MCP must be deferred so this request can finish
    # before the serving process is terminated.
    if os.getenv("TERMUX_MCP_TOOL_CONTEXT") == "1" and action == "keep" and process.is_running():
        old_pid = process.read_pid()
        worker_pid = process.schedule_server_restart(old_pid)
        print(f"Server restart scheduled (worker pid {worker_pid}); tunnel kept.")
        return 0

    # 1. Stop the server only — never touch the tunnel unless asked.
    if process.is_running():
        pid = process.read_pid()
        if not process.stop_server():
            print(f"ERROR: server pid {pid} did not stop; restart aborted.")
            return 1
        print(f"Server stopped (pid {pid})")
    else:
        process.clear_pid()
        print("Server is not running.")

    # 2. Tunnel handling per the requested action.
    if action in ("rebuild", "stop"):
        if process.tunnel_is_running():
            tpid = process.read_tunnel_pid()
            process.kill_pid(tpid)
            process.clear_tunnel_pid()
            print(f"Tunnel stopped (pid {tpid})")
        else:
            process.clear_tunnel_pid()
        # The old public URL is no longer valid once the tunnel is gone.
        clear_public_url()
    else:  # keep
        # A named Cloudflare tunnel may have been started outside this launcher
        # (for example a shared multi-route tunnel). Adopt it before declaring
        # that there is no tunnel to keep.
        if not process.tunnel_is_running():
            process.adopt_named_cloudflare_tunnel(named_config, named_tunnel or "termux-mcp")
        if process.tunnel_is_running():
            print(f"Tunnel kept (pid {process.read_tunnel_pid()})")
            pub = get_public_url()
            if pub:
                print(f"Public MCP URL kept: {pub}/mcp")
        else:
            # No live tunnel — drop any stale public URL so the restarted
            # server does not advertise a dead endpoint.
            clear_public_url()
            print("No running tunnel to keep.")

    # Small pause so the ports are released before rebinding.
    time.sleep(1)

    # 3. Start the server. Rebuild passes the requested provider; keep/stop
    # start without touching the tunnel (a kept tunnel still forwards to the
    # same MCP port, and the persisted public_url is re-read by the server's
    # transport-security watcher on startup).
    start_args = argparse.Namespace()
    if action == "rebuild":
        start_args.no_tunnel = False
        start_args.tunnel = args.tunnel
    else:
        start_args.no_tunnel = True
        start_args.tunnel = "none"
    return cmd_start(start_args)


def cmd_status() -> int:
    running = process.is_running()
    pid = process.read_pid()
    print(f"Server: {'RUNNING' if running else 'STOPPED'}" + (f" (pid {pid})" if pid else ""))
    print(f"REST http://127.0.0.1:{PORT}: {'OK' if process.port_open(PORT) else 'DOWN'}")
    if MCP_ENABLED:
        mcp_listening = process.port_open(MCP_PORT)
        print(f"MCP port {MCP_PORT}: {'LISTENING' if mcp_listening else 'DOWN'}")
        if mcp_listening:
            if os.getenv("TERMUX_MCP_TOOL_CONTEXT") == "1":
                print("MCP initialize: SKIPPED — current command is running inside MCP")
            else:
                mcp_ok, mcp_detail = process.mcp_initialize_probe(MCP_PORT, AUTH_TOKEN, timeout=3)
                print(f"MCP initialize: {'OK' if mcp_ok else 'FAIL'} — {mcp_detail}")
    print(f"Auth: {'enabled' if token_configured() else 'DISABLED'}")
    from . import config
    print(f"Client: {config.CLIENT_TARGET}")
    print(f"Permissions: {config.PERMISSION_MODE}")
    if config.LAN_HOST:
        print(f"LAN: enabled — http://{config.LAN_HOST}:{MCP_PORT}/mcp")
    else:
        print("LAN: disabled (localhost only)")
    if WORKSPACE_ROOT:
        print(f"Workspace: {WORKSPACE_ROOT}")
    if process.tunnel_is_running():
        print(f"Tunnel: running (pid {process.read_tunnel_pid()})")
    # OAuth / discovery state — never print tokens or client secrets.
    from . import oauth
    if oauth.oauth_enabled():
        print("OAuth resource metadata: enabled")
        issuer = oauth.get_issuer()
        print(f"OAuth issuer: {issuer or 'not resolvable (auto + no public URL)'}")
    else:
        print("OAuth resource metadata: disabled (static Bearer mode)")
    pub = get_public_url()
    source = public_url_source()
    if pub:
        print(f"Public MCP URL: {source} — {pub}/mcp")
    else:
        print("Public MCP URL: unavailable")
    return 0 if running else 1


def cmd_url() -> int:
    """Print the current public URL without exposing any auth secret."""
    pub = get_public_url()
    if not pub:
        print("Public MCP URL: unavailable")
        print("Run: termux-mcp start")
        return 1
    print(pub.rstrip("/") + "/mcp")
    source = public_url_source()
    if source == "runtime":
        if process.tunnel_is_running():
            print(f"Free tunnel: preserved (pid {process.read_tunnel_pid()})")
            print("Server-only restart keeps this URL. Do not rebuild the tunnel unless needed.")
        else:
            print("Free tunnel: offline")
            print("The next anonymous tunnel may receive a different URL.")
    else:
        print("URL source: configured")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    text = process.tail_log(args.n)
    if not text:
        print("No log output yet.")
        return 0
    print(text, end="")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    if args.rotate:
        token = rotate_token()
        print("New auth token generated and saved to config (chmod 600).")
        if args.show:
            print(f"Token: {token}")
        print("Restart the server for the new token to take effect: termux-mcp restart")
        return 0
    if token_configured():
        print("Auth token: configured")
        if args.show:
            print(f"Token: {AUTH_TOKEN}")
        else:
            print("Use 'termux-mcp token --show' to display it.")
    else:
        print("Auth token: NOT configured")
        print("Run 'termux-mcp start' to auto-generate one, or 'termux-mcp token --rotate'.")
    return 0


def cmd_guide() -> int:
    from .guide import run_guide
    return run_guide()


def cmd_setup(args: argparse.Namespace) -> int:
    from .onboarding import run_setup
    return run_setup(args, cmd_start)


def cmd_permissions(args: argparse.Namespace) -> int:
    from . import config
    from .permissions import MODES, status

    if args.permissions_action == "set":
        config.set_permission_mode(args.mode)
        print(f"✓ 权限模式已设为 {args.mode}: {MODES[args.mode]}")
        if process.is_running():
            print("重启后生效：termux-mcp restart")
        return 0
    current = status()
    print(f"当前权限：{current['mode']}")
    print(current["description"])
    print("修改：termux-mcp permissions set <read-only|standard|full>")
    return 0


# ── Named domains ────────────────────────────────────────────────────────────

def cmd_domain(args: argparse.Namespace) -> int:
    from . import config, named_tunnel

    path = getattr(args, "config", None) or named_tunnel.DEFAULT_CONFIG
    try:
        if args.domain_command == "guide":
            hostname = args.hostname or config.CONNECTION_VALUE
            state = named_tunnel.inspect_cloudflare()
            if not hostname and os.path.isfile(path):
                rules = named_tunnel.list_ingress(path)
                mcp_service = f"http://127.0.0.1:{MCP_PORT}"
                match = next((rule for rule in rules if rule.service == mcp_service), None)
                if match:
                    hostname = match.hostname
            print("\n( Ꙭ) 自有域名检查")
            print(f"  cloudflared：{'✓ 已安装' if state['installed'] else '○ 未安装'}")
            print(f"  Cloudflare 授权：{'✓ 已登录' if state['authenticated'] else '○ 还没登录'}")
            print(f"  Named Tunnel：{len(state['tunnels'])} 个")
            print(f"  配置文件：{'✓ 已存在' if state['config_exists'] else '○ 还没有'}")
            if hostname:
                print(f"  目标地址：https://{hostname}/mcp")
            if not state['installed']:
                print("\n下一步只做这一件事：pkg install -y cloudflared")
            elif not state['authenticated']:
                print("\n下一步只做这一件事：cloudflared tunnel login")
                print("浏览器授权完成后，再运行 termux-mcp domain guide。")
            elif not state['tunnels']:
                print("\n下一步只做这一件事：cloudflared tunnel create termux-mcp")
                print("创建完成后，再运行 termux-mcp domain guide。")
            elif not state['config_exists']:
                chosen = state['tunnels'][0]['name'] or state['tunnels'][0]['id']
                print(f"\n已经找到 Tunnel：{chosen}")
                print("还缺 ~/.cloudflared/config.yml；为了避免覆盖你的现有设置，向导不会静默创建。")
                print("README 的“自有域名”章节给了最小模板。")
            elif hostname:
                chosen = state['tunnels'][0]['name'] or state['tunnels'][0]['id']
                configured = any(rule.hostname == hostname for rule in named_tunnel.list_ingress(path))
                if configured:
                    print(f"\n✓ {hostname} 已经在 ingress 中，不需要重新 setup。")
                    print(f"启动现有 Named Tunnel：cloudflared tunnel --config {path} run {chosen}")
                else:
                    print("\n基础条件都齐啦。真正修改 ingress / DNS 前需要你明确执行：")
                    print(f"  termux-mcp domain add {hostname} --port {config.MCP_PORT} --tunnel {chosen}")
                    print("这个命令会先备份并校验配置，再创建 DNS route。")
            else:
                print("\n还缺目标域名。先运行 termux-mcp setup --force 选择‘我有自己的域名’。")
            return 0
        if args.domain_command == "list":
            rules = named_tunnel.list_ingress(path)
            if not rules:
                print("No hostname ingress routes configured.")
            for rule in rules:
                print(f"{rule.hostname} -> {rule.service}")
            return 0

        if args.domain_command == "plan":
            planned = named_tunnel.plan_domain_migration(
                args.new_domain, path=path, from_domain=args.from_domain
            )
            print("Domain migration preview (no changes made):")
            for old, new in planned:
                print(f"  {old.hostname} -> {new.hostname}  [{old.service}]")
            return 0

        if args.domain_command == "migrate":
            backup, planned = named_tunnel.migrate_ingress_domain(
                args.new_domain, path=path, from_domain=args.from_domain
            )
            if backup:
                print(f"Ingress hostnames migrated and validated. Backup: {backup}")
            else:
                print("Ingress hostnames already match the requested domain.")
            if not args.no_dns:
                for _, new in planned:
                    named_tunnel.route_dns(args.tunnel, new.hostname)
                    print(f"DNS route ready: {new.hostname}")
            print("Restart the named cloudflared tunnel to load the new ingress.")
            print("Review OAuth/public URL environment variables before switching clients.")
            return 0

        backup = named_tunnel.add_ingress(args.hostname, args.port, path=path)
        if backup:
            print(f"Ingress added and validated. Backup: {backup}")
        else:
            print("Ingress already configured.")
        if not args.no_dns:
            named_tunnel.route_dns(args.tunnel, args.hostname)
            print(f"DNS route ready: {args.hostname}")
        print("Restart the named cloudflared tunnel to load the new ingress.")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Domain error: {exc}", file=sys.stderr)
        return 1


# ── doctor ───────────────────────────────────────────────────────────────────

def _pkg_version(name: str) -> Optional[str]:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _check(
    checks: List[Dict[str, str]],
    check_id: str,
    name: str,
    ok: bool,
    detail: str = "",
    warn: bool = False,
    emit: bool = True,
) -> None:
    status = "WARN" if warn else ("PASS" if ok else "FAIL")
    if emit:
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    checks.append({"id": check_id, "name": name, "status": status, "detail": detail})


def _version_in_range(
    value: Optional[str], minimum: str, maximum_exclusive: str
) -> bool:
    if value is None:
        return False
    try:
        parsed = Version(value)
        return Version(minimum) <= parsed < Version(maximum_exclusive)
    except InvalidVersion:
        return False


def cmd_doctor(json_output: bool = False) -> int:
    checks: List[Dict[str, str]] = []
    emit = not json_output
    if emit:
        print(f"termux-mcp doctor (v{__version__})\n")

    # OS / Termux
    is_termux = os.environ.get("PREFIX", "").startswith("/data/data/com.termux")
    _check(checks, "termux_environment", "Termux environment", is_termux,
           "PREFIX detected" if is_termux else "not Termux (running on desktop?)",
           warn=not is_termux, emit=emit)

    # Python
    py = sys.version.split()[0]
    _check(checks, "python_version", "Python version", sys.version_info >= (3, 10), py,
           emit=emit)

    # Package / deps
    pkg = _pkg_version("termux-mcp")
    _check(checks, "package_installed", "termux-mcp installed", pkg is not None,
           pkg or "not installed via pip (running from source is fine)", warn=pkg is None,
           emit=emit)
    mcp_ver = _pkg_version("mcp")
    _check(checks, "mcp_sdk_version", "MCP SDK (mcp>=1.28,<2)",
           _version_in_range(mcp_ver, "1.28", "2"), mcp_ver or "not installed",
           emit=emit)
    uvi = _pkg_version("uvicorn")
    _check(checks, "uvicorn", "uvicorn", uvi is not None, uvi or "not installed",
           emit=emit)

    # Auth
    auth_ok = token_configured()
    _check(checks, "auth_token", "Auth token configured", auth_ok,
           "enabled" if auth_ok else "not configured — start will generate one",
           warn=not auth_ok, emit=emit)

    # OAuth / discovery (no secrets printed; absence is not a FAIL when
    # static Bearer mode is intentionally used).
    from . import oauth
    if oauth.oauth_enabled():
        issuer = oauth.get_issuer()
        _check(checks, "oauth_metadata", "OAuth resource metadata", True, "enabled",
               emit=emit)
        _check(checks, "oauth_issuer", "OAuth issuer", bool(issuer),
               issuer or "auto — no public URL yet", warn=not issuer, emit=emit)
        pub = get_public_url()
        _check(checks, "public_url", "Public MCP URL", bool(pub),
               f"{pub}/mcp" if pub else "unavailable", warn=not pub, emit=emit)
    else:
        _check(checks, "oauth_metadata", "OAuth resource metadata", True,
               "disabled (static Bearer mode)", emit=emit)

    # Workspace
    if WORKSPACE_ROOT:
        _check(checks, "workspace_root", "Workspace root",
               os.path.isdir(WORKSPACE_ROOT), WORKSPACE_ROOT, emit=emit)
    else:
        _check(checks, "workspace_root", "Workspace root", True,
               "not set (MCP filesystem tools unrestricted)", warn=True, emit=emit)

    # Closed ports are expected before first start. An occupied port while our
    # process is stopped is the actionable failure.
    running = process.is_running()
    rest_open = process.port_open(PORT)
    if running:
        _check(checks, "rest_port", f"REST port {PORT}", rest_open,
               "listening" if rest_open else "server running but port not listening",
               emit=emit)
    else:
        _check(checks, "rest_port", f"REST port {PORT}", not rest_open,
               "occupied by another process" if rest_open else "not listening; server stopped",
               warn=not rest_open, emit=emit)
    if MCP_ENABLED:
        mcp_open = process.port_open(MCP_PORT)
        if running:
            _check(checks, "mcp_port", f"MCP port {MCP_PORT}", mcp_open,
                   "listening" if mcp_open else "server running but port not listening",
                   emit=emit)
        else:
            _check(checks, "mcp_port", f"MCP port {MCP_PORT}", not mcp_open,
                   "occupied by another process" if mcp_open else "not listening; server stopped",
                   warn=not mcp_open, emit=emit)

    _check(checks, "server_process", "Server process", running,
           f"pid {process.read_pid()}" if running else "not running", warn=not running,
           emit=emit)

    # LAN exposure is explicit and diagnosable; disabled is a healthy default.
    lan_host = config_mod.LAN_HOST
    lan_enabled = bool(lan_host) and MCP_HOST not in ("127.0.0.1", "localhost")
    _check(checks, "lan_mode", "LAN mode", True,
           f"enabled — http://{lan_host}:{MCP_PORT}/mcp" if lan_enabled
           else "disabled (localhost only)", emit=emit)

    # Tunnel deps
    for name in ("ssh", "cloudflared"):
        import shutil
        found = shutil.which(name) is not None
        _check(checks, f"tunnel_{name}", f"tunnel dep: {name}", found,
               shutil.which(name) or "not installed", warn=not found, emit=emit)

    # Public edge health is separate from local process/protocol health.
    pub = get_public_url()
    if pub:
        public_ok, public_detail = process.public_http_probe(pub, timeout=5.0)
        _check(checks, "public_transport", "Public transport", public_ok, public_detail,
               warn=not public_ok, emit=emit)

    # Localhost MCP protocol health: a real authenticated initialize request.
    if MCP_ENABLED and process.port_open(MCP_PORT):
        if os.getenv("TERMUX_MCP_TOOL_CONTEXT") == "1":
            _check(checks, "mcp_health", "MCP initialize", True,
                   "skipped inside MCP tool context", warn=True, emit=emit)
        else:
            mcp_ok, mcp_detail = process.mcp_initialize_probe(MCP_PORT, AUTH_TOKEN, timeout=5)
            _check(checks, "mcp_health", "MCP initialize", mcp_ok, mcp_detail, emit=emit)
    else:
        _check(checks, "mcp_health", "MCP initialize", False,
               "MCP port not listening", warn=True, emit=emit)

    fails = [c for c in checks if c["status"] == "FAIL"]
    warns = [c for c in checks if c["status"] == "WARN"]
    summary: Dict[str, Any] = {
        "pass": len(checks) - len(fails) - len(warns),
        "warn": len(warns),
        "fail": len(fails),
    }
    if json_output:
        print(json.dumps({"version": __version__, "summary": summary, "checks": checks},
                         ensure_ascii=False, indent=2))
        return 1 if fails else 0

    print()
    if fails:
        print(f"{summary['fail']} FAIL, {summary['warn']} WARN, {summary['pass']} PASS")
        print("Fix the FAIL items above, then re-run 'termux-mcp doctor'.")
        return 1
    print(f"{summary['pass']} PASS, {summary['warn']} WARN, 0 FAIL")
    if warns:
        print("WARN items are optional — see details above.")
    return 0


# ── Entry point ──────────────────────────────────────────────────────────────

def run(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    if args.command is None:
        # Backward compatible: bare `termux-mcp` runs the server in the
        # foreground (same as `python -m termux_mcp`).
        from .server import run as run_server
        run_server()
        return 0

    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop()
    if args.command == "restart":
        return cmd_restart(args)
    if args.command == "status":
        return cmd_status()
    if args.command == "apps":
        from . import app_registry
        try:
            if args.apps_action == "list":
                print(json.dumps(app_registry.list_apps(args.category), indent=2, ensure_ascii=False)); return 0
            if args.apps_action == "show":
                print(json.dumps(app_registry.inspect(args.app), indent=2, ensure_ascii=False)); return 0
            if args.apps_action == "doctor":
                result=app_registry.doctor(args.app); print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("ready") else 1
            if args.apps_action == "authorize":
                result=app_registry.authorize(args.app,args.action); print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("allowed") else 1
            if args.apps_action == "launch":
                result=app_registry.launch(args.app); print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("ok") else 1
            if args.apps_action == "browse":
                result=app_registry.browse(args.app,max_depth=args.depth); print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("ok") else 1
            if args.apps_action == "act":
                result=app_registry.act(args.app,args.action,text=args.text,view_id=args.view_id,desc=args.desc,index=args.index); print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("ok") else 1
        except KeyError as exc:
            print(f"Unknown app: {exc.args[0]}", file=sys.stderr); return 2

    if args.command == "components":
        from . import governance
        cs = governance.load_registry()
        if args.components_action == "list":
            for name in cs: print(name)
            return 0
        if args.components_action == "inspect":
            if args.component not in cs:
                print(f"Unknown component: {args.component}", file=sys.stderr); return 2
            print(json.dumps(governance.inspect_component(args.component, cs), indent=2, ensure_ascii=False)); return 0
        if args.components_action == "topology":
            for row in governance.topology(cs):
                deps = ",".join(row["depends_on"]) or "-"
                mark = "DRIFT" if row["drift"] else "OK"
                print(f'{row["id"]:26} {row["actual"]:7} desired={row["desired"]:7} owner={row["owner"]} deps={deps} {mark}')
            return 0
        if args.components_action in ("recover-plan", "recover"):
            if args.component not in cs:
                print(f"Unknown component: {args.component}", file=sys.stderr); return 2
            execute = args.components_action == "recover"
            result = governance.recover_component(args.component, cs, execute=execute)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if execute and not result.get("allowed"): return 3
            return int(result.get("returncode",0))
        rows = governance.reconcile(cs)
        for row in rows:
            mark = "DRIFT" if row["drift"] else "OK"
            print(f'{row["id"]:26} desired={row["desired"]:7} actual={row["actual"]:7} {mark}')
        return 1 if any(r["drift"] for r in rows) else 0
    if args.command == "url":
        return cmd_url()
    if args.command == "guide":
        return cmd_guide()
    if args.command == "logs":
        return cmd_logs(args)
    if args.command == "doctor":
        return cmd_doctor(args.json_output)
    if args.command == "update":
        if args.update_action == "check":
            from .update_discovery import check_updates
            try:
                result = check_updates(__version__)
            except Exception as exc:
                if args.json_output:
                    print(json.dumps({"installed": __version__, "status": "check_failed", "error": str(exc)}, ensure_ascii=False))
                else:
                    print(f"Installed: {__version__}")
                    print(f"Update check failed: {exc}")
                return 2
            if args.json_output:
                print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
            else:
                print(f"Installed:      {result.installed}")
                print(f"Latest release: {result.latest_tag or 'none'}")
                print(f"Status:         {result.status}")
                print(result.detail)
            return 0
    if args.command == "token":
        return cmd_token(args)
    if args.command == "setup":
        return cmd_setup(args)
    if args.command == "permissions":
        return cmd_permissions(args)
    if args.command == "domain":
        return cmd_domain(args)
    return 0


if __name__ == "__main__":
    sys.exit(run())
