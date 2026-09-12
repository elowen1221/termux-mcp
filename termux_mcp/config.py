"""Configuration for termux-mcp.

Values are resolved in this order (highest priority first):
  1. Environment variables (TERMUX_MCP_*)
  2. Persistent config file  ~/.config/termux-mcp/config.env
  3. Built-in defaults

The config file is created automatically by `termux-mcp start` / `ensure_token()`
with mode 0600 so the auth token never leaks to other users. Tokens are never
printed to logs and never accepted in URL query parameters.
"""

import os
import re
import secrets

HOME: str = os.environ.get("HOME", "/data/data/com.termux/files/home")

# Profile isolation: TERMUX_MCP_PROFILE=<name> runs a fully separate instance
# (config dir, state dir, default ports) so a stable and a dev/test instance
# can coexist on one device without clobbering each other's PID / log /
# public_url / token / OAuth state. Explicit TERMUX_MCP_* env vars still win.
PROFILE: str = os.environ.get("TERMUX_MCP_PROFILE", "").strip()
if PROFILE and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", PROFILE):
    raise SystemExit(
        "Invalid TERMUX_MCP_PROFILE: use 1-32 letters, digits, underscores, or hyphens"
    )
_PROFILE_SUFFIX = f"-{PROFILE}" if PROFILE else ""

CONFIG_DIR: str = os.path.join(HOME, ".config", f"termux-mcp{_PROFILE_SUFFIX}")
CONFIG_FILE: str = os.path.join(CONFIG_DIR, "config.env")
STATE_DIR: str = os.path.join(HOME, ".local", "state", f"termux-mcp{_PROFILE_SUFFIX}")


def _load_config_file() -> dict:
    """Load key=value pairs from the config file (if present)."""
    values = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_FILE_VALUES: dict = _load_config_file()


def _env_or_file(name: str, default: str) -> str:
    """Environment variables override the config file."""
    if name in os.environ:
        return os.environ[name]
    return _FILE_VALUES.get(name, default)


def _int_setting(name: str, default: str, minimum: int, maximum: int) -> int:
    """Read a bounded integer setting and fail with an actionable message."""
    raw = _env_or_file(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise SystemExit(
            f"Invalid {name}={raw!r}: expected an integer from {minimum} to {maximum}"
        ) from None
    if not minimum <= value <= maximum:
        raise SystemExit(
            f"Invalid {name}={raw!r}: expected a value from {minimum} to {maximum}"
        )
    return value


def _write_config(updates: dict) -> None:
    """Persist config values to the config file (mode 0600)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    values = dict(_FILE_VALUES)
    values.update(updates)
    lines = [
        "# termux-mcp configuration (auto-generated)",
        "# This file may contain secrets and is chmod 600.",
        "# Environment variables TERMUX_MCP_* override these values.",
    ]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, CONFIG_FILE)
    _FILE_VALUES.clear()
    _FILE_VALUES.update(values)


# Default ports shift by +10000 when a profile is active so a dev/test
# instance never collides with the stable one. Explicit TERMUX_MCP_PORT /
# TERMUX_MCP_MCP_PORT (env or profile config file) still win.
_DEFAULT_PORT = "18080" if PROFILE else "8080"
_DEFAULT_MCP_PORT = "18765" if PROFILE else "8765"
PORT: int = _int_setting("TERMUX_MCP_PORT", _DEFAULT_PORT, 1, 65535)
HOST: str = _env_or_file("TERMUX_MCP_HOST", "127.0.0.1")

# Command timeout in seconds. 0 (default) = NO timeout — long operations
# like pkg update/upgrade/install run until they finish. Set a positive
# value (e.g. 600) to re-enable the watchdog kill.
COMMAND_TIMEOUT: int = _int_setting("TERMUX_MCP_TIMEOUT", "0", 0, 86400)

# Cap on streamed command output sent to clients. Output beyond this is
# drained (process keeps running) but discarded, with a truncation marker
# appended. Keeps LLM tool results small and token-efficient.
MAX_OUTPUT_BYTES: int = _int_setting(
    "TERMUX_MCP_MAX_OUTPUT", "20000", 1024, 10 * 1024 * 1024
)

AUTH_TOKEN: str = _env_or_file("TERMUX_MCP_AUTH_TOKEN", "")
REQUIRE_AUTH: bool = bool(AUTH_TOKEN)

# OAuth / auth-discovery (RFC 9728 protected resource metadata).
# TERMUX_MCP_OAUTH_ISSUER enables OAuth mode. The special value "auto"
# resolves the issuer to the current public URL (runtime tunnel URL, else
# TERMUX_MCP_PUBLIC_URL) so metadata stays correct even though tunnel URLs
# change on restart. TERMUX_MCP_PUBLIC_URL is the externally visible MCP
# base URL (e.g. https://mcp.example.com) used for the protected-resource
# `resource` field and the WWW-Authenticate resource_metadata challenge.
PUBLIC_URL: str = _env_or_file("TERMUX_MCP_PUBLIC_URL", "").strip()
OAUTH_ISSUER: str = _env_or_file("TERMUX_MCP_OAUTH_ISSUER", "").strip()
OAUTH_SCOPES: str = _env_or_file("TERMUX_MCP_OAUTH_SCOPES", "mcp:read mcp:write").strip()

# Runtime public URL, written by the launcher after a tunnel starts so the
# server process (a separate subprocess) can serve correct OAuth metadata
# without trusting Host/X-Forwarded-* headers. Profile-aware via STATE_DIR.
PUBLIC_URL_FILE: str = os.path.join(STATE_DIR, "public_url")


def set_public_url(url: str) -> None:
    """Record the externally reachable MCP base URL (runtime, from tunnel)."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return
    os.makedirs(os.path.dirname(PUBLIC_URL_FILE), exist_ok=True)
    with open(PUBLIC_URL_FILE, "w", encoding="utf-8") as f:
        f.write(url)


def clear_public_url() -> None:
    """Drop the runtime public URL (used when the tunnel stops)."""
    try:
        os.remove(PUBLIC_URL_FILE)
    except OSError:
        pass


def get_public_url() -> str:
    """Current externally reachable MCP base URL (runtime > config)."""
    try:
        with open(PUBLIC_URL_FILE, "r", encoding="utf-8") as f:
            url = f.read().strip().rstrip("/")
        if url:
            return url
    except OSError:
        pass
    return PUBLIC_URL.rstrip("/")


def public_url_source() -> str:
    """Where the public URL comes from: "runtime", "configured", or ""."""
    try:
        with open(PUBLIC_URL_FILE, "r", encoding="utf-8") as f:
            if f.read().strip():
                return "runtime"
    except OSError:
        pass
    return "configured" if PUBLIC_URL else ""

# MCP Streamable HTTP layer (official `mcp` Python SDK).
MCP_ENABLED: bool = _env_or_file("TERMUX_MCP_MCP_ENABLED", "1").lower() in (
    "1", "true", "yes", "on",
)
MCP_HOST: str = _env_or_file("TERMUX_MCP_MCP_HOST", HOST)
MCP_PORT: int = _int_setting("TERMUX_MCP_MCP_PORT", _DEFAULT_MCP_PORT, 1, 65535)
if MCP_ENABLED and MCP_PORT == PORT:
    raise SystemExit("Invalid configuration: REST and MCP ports must be different")

# Optional workspace root for MCP filesystem tools. When set, MCP
# read_file/write_file/list_files/make_directory are restricted to paths
# inside this root (resolved with realpath). REST is unaffected.
WORKSPACE_ROOT: str = _env_or_file("TERMUX_MCP_WORKSPACE", "").strip()

# User-selected capability level. This is intentionally independent from the
# process profile above: profiles isolate instances, while permission modes
# decide what an attached AI may do through an instance.
PERMISSION_MODE: str = _env_or_file("TERMUX_MCP_PERMISSIONS", "standard").strip().lower()
if PERMISSION_MODE not in ("read-only", "standard", "full"):
    raise SystemExit(
        "Invalid TERMUX_MCP_PERMISSIONS: use read-only, standard, or full"
    )
CLIENT_TARGET: str = _env_or_file("TERMUX_MCP_CLIENT", "chatgpt").strip().lower()
if CLIENT_TARGET not in ("chatgpt", "claude", "grok"):
    raise SystemExit("Invalid TERMUX_MCP_CLIENT: use chatgpt, claude, or grok")
SETUP_COMPLETE: bool = _env_or_file("TERMUX_MCP_SETUP_COMPLETE", "0").lower() in (
    "1", "true", "yes", "on",
)

# Tunnel provider order for `termux-mcp start --tunnel auto`.
TUNNEL_PROVIDERS: list = [
    p.strip()
    for p in _env_or_file("TERMUX_MCP_TUNNEL_PROVIDERS", "pinggy,cloudflare,localhost-run").split(",")
    if p.strip()
]
# Seconds to wait for a tunnel provider to produce a public URL before
# terminating it and trying the next one.
TUNNEL_TIMEOUT: int = _int_setting("TERMUX_MCP_TUNNEL_TIMEOUT", "45", 1, 600)

AUTO_INPUT_INTERVAL: float = 0.5
PORT_POLL_INTERVAL: float = 0.3
AUTO_YES_COMMANDS: list[str] = [
    "pkg install",
    "pkg upgrade",
    "pkg update",
    "apt install",
    "apt upgrade",
    "apt update",
]


def ensure_token() -> str:
    """Ensure an auth token exists — generate and persist one if missing.

    Returns the active token. Updates the module-level AUTH_TOKEN /
    REQUIRE_AUTH so the running process enforces auth immediately.
    """
    global AUTH_TOKEN, REQUIRE_AUTH
    if AUTH_TOKEN:
        return AUTH_TOKEN
    token = secrets.token_urlsafe(32)
    _write_config({"TERMUX_MCP_AUTH_TOKEN": token})
    AUTH_TOKEN = token
    REQUIRE_AUTH = True
    return token


def rotate_token() -> str:
    """Generate a fresh auth token and persist it. Returns the new token."""
    global AUTH_TOKEN, REQUIRE_AUTH
    token = secrets.token_urlsafe(32)
    _write_config({"TERMUX_MCP_AUTH_TOKEN": token})
    AUTH_TOKEN = token
    REQUIRE_AUTH = True
    return token


def token_configured() -> bool:
    """True when an auth token is configured (env or config file)."""
    return bool(AUTH_TOKEN)


def save_user_preferences(client: str, permissions: str) -> None:
    """Persist onboarding choices and update this process immediately."""
    client = client.strip().lower()
    permissions = permissions.strip().lower()
    if client not in ("chatgpt", "claude", "grok"):
        raise ValueError("client must be chatgpt, claude, or grok")
    if permissions not in ("read-only", "standard", "full"):
        raise ValueError("permissions must be read-only, standard, or full")
    _write_config({
        "TERMUX_MCP_CLIENT": client,
        "TERMUX_MCP_PERMISSIONS": permissions,
        "TERMUX_MCP_SETUP_COMPLETE": "1",
        # Auto mode lets the public tunnel become the OAuth issuer, so the
        # user can paste one URL instead of copying a Bearer token separately.
        "TERMUX_MCP_OAUTH_ISSUER": "auto",
    })
    global CLIENT_TARGET, PERMISSION_MODE, SETUP_COMPLETE, OAUTH_ISSUER
    CLIENT_TARGET = client
    PERMISSION_MODE = permissions
    SETUP_COMPLETE = True
    OAUTH_ISSUER = "auto"


def set_permission_mode(mode: str) -> None:
    """Persist a permission mode selected by the device owner."""
    mode = mode.strip().lower()
    if mode not in ("read-only", "standard", "full"):
        raise ValueError("permissions must be read-only, standard, or full")
    _write_config({"TERMUX_MCP_PERMISSIONS": mode})
    global PERMISSION_MODE
    PERMISSION_MODE = mode
