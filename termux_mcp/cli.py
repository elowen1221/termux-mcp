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
    public_url_source,
    rotate_token,
    set_public_url,
    token_configured,
)

TUNNEL_CHOICES = ["auto", "pinggy", "cloudflare", "localhost-run", "none"]


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

    sub.add_parser("stop", help="Stop the running server and tunnel")

    p_restart = sub.add_parser("restart", help="Restart the server (tunnel kept by default)")
    p_restart.add_argument(
        "--tunnel", default=None, choices=TUNNEL_CHOICES,
        help="Rebuild the tunnel with this provider (default: keep the running tunnel)",
    )
    p_restart.add_argument(
        "--no-tunnel", action="store_true",
        help="Stop the tunnel and restart the server without one",
    )

    sub.add_parser("status", help="Show server / tunnel / auth status")

    p_logs = sub.add_parser("logs", help="Show recent server logs")
    p_logs.add_argument("-n", type=int, default=50, help="Number of lines (default 50)")

    p_doctor = sub.add_parser("doctor", help="Run self-checks")
    p_doctor.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit a machine-readable diagnostic report",
    )

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

def cmd_start(args: argparse.Namespace) -> int:
    # A. Load config / ensure token.
    token = ensure_token()
    print(f"Auth token: configured (length {len(token)})")

    # B. Avoid duplicate instances.
    if process.is_running():
        print(
            f"termux-mcp is already running (pid {process.read_pid()}). "
            "Use 'termux-mcp status' or 'termux-mcp restart'."
        )
        return 1

    # C. Start the server.
    pid = process.start_server()
    print(f"Server started (pid {pid})")

    # D. Wait for REST + MCP health.
    rest_ok = process.wait_http(PORT)
    mcp_ok = process.wait_http(MCP_PORT) if MCP_ENABLED else True
    print(f"REST http://127.0.0.1:{PORT}: {'OK' if rest_ok else 'NOT RESPONDING'}")
    if MCP_ENABLED:
        print(f"MCP  http://127.0.0.1:{MCP_PORT}/mcp: {'OK' if mcp_ok else 'NOT RESPONDING'}")
    if not rest_ok:
        print("Server did not become healthy. Check 'termux-mcp logs'.")
        return 1

    # E/F/G/H. Tunnel.
    choice = "none" if args.no_tunnel else args.tunnel
    if choice != "none":
        result = tunnel_mod.start_tunnel(MCP_PORT, choice)
        if result.url:
            mcp_url = result.url.rstrip("/") + "/mcp"
            print(f"Tunnel ({result.provider}): {mcp_url}")
            if result.process and result.process.pid:
                process.write_tunnel_pid(result.process.pid)
            # Propagate the real public URL so OAuth metadata / challenges
            # served by the server process use it (never Host headers).
            set_public_url(result.url)
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
    if choice != "none" and result.url:
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
        process.stop_server()
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

    # 1. Stop the server only — never touch the tunnel unless asked.
    if process.is_running():
        pid = process.read_pid()
        process.stop_server()
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
        print(f"MCP  http://127.0.0.1:{MCP_PORT}/mcp: {'OK' if process.port_open(MCP_PORT) else 'DOWN'}")
    print(f"Auth: {'enabled' if token_configured() else 'DISABLED'}")
    from . import config
    print(f"Client: {config.CLIENT_TARGET}")
    print(f"Permissions: {config.PERMISSION_MODE}")
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
    from . import named_tunnel

    path = args.config or named_tunnel.DEFAULT_CONFIG
    try:
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

    # Tunnel deps
    for name in ("ssh", "cloudflared"):
        import shutil
        found = shutil.which(name) is not None
        _check(checks, f"tunnel_{name}", f"tunnel dep: {name}", found,
               shutil.which(name) or "not installed", warn=not found, emit=emit)

    # Localhost MCP health (authenticated probe)
    if MCP_ENABLED and process.port_open(MCP_PORT):
        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{MCP_PORT}/mcp",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                _check(checks, "mcp_health", "MCP health", True, "responded",
                       emit=emit)
            except urllib.error.HTTPError as e:
                _check(checks, "mcp_health", "MCP health", e.code == 401,
                       f"HTTP {e.code}" + (" (auth working)" if e.code == 401 else ""),
                       emit=emit)
        except Exception as e:
            _check(checks, "mcp_health", "MCP health", False, str(e), emit=emit)
    else:
        _check(checks, "mcp_health", "MCP health", False,
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
    if args.command == "logs":
        return cmd_logs(args)
    if args.command == "doctor":
        return cmd_doctor(args.json_output)
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
