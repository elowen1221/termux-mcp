"""Tunnel providers for exposing the local MCP endpoint publicly.

Supported providers (order is configurable via TERMUX_MCP_TUNNEL_PROVIDERS):
  * pinggy        — `ssh -p 443 -R0:localhost:<port> a@free.pinggy.io`
  * cloudflare    — `cloudflared tunnel --url http://127.0.0.1:<port>`
  * localhost-run — `ssh -R 80:localhost:<port> nokey@localhost.run`

`start_tunnel(port, "auto")` tries each available provider in order, gives
each a bounded timeout, terminates a provider that hangs, and returns the
first public HTTPS URL that appears. A parsed URL is not enough: the URL
must actually answer over the public internet (see wait_for_public_url)
before the provider counts as successful. Tunnel URLs are
deployment-sensitive and are never uploaded anywhere.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from . import process
from .config import TUNNEL_PROVIDERS, TUNNEL_TIMEOUT

# URL patterns per provider, in priority order. These are STRICT: they only
# match real tunnel hostnames, never dashboard/management pages. Pinggy
# prints its dashboard/upgrade links (e.g. https://dashboard.pinggy.io)
# alongside the actual tunnel URL, so the parser must skip anything that is
# not a tunnel hostname.
_URL_PATTERNS = {
    "pinggy": [
        r"https://[a-z0-9][a-z0-9-]*\.a\.free\.pinggy\.link$",
        r"https://[a-z0-9][a-z0-9-]*\.a\.pinggy\.link$",
        r"https://[a-z0-9][a-z0-9-]*\.free\.pinggy\.net$",
        r"https://[a-z0-9][a-z0-9-]*\.pinggy-free\.link$",
        r"https://[a-z0-9][a-z0-9-]*\.a\.free\.pinggy\.online$",
    ],
    "cloudflare": [
        r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com$",
    ],
    "localhost-run": [
        r"https://[a-z0-9][a-z0-9-]*\.lhr\.life$",
        r"https://[a-z0-9][a-z0-9-]*\.lhr\.rocks$",
    ],
}

# Hostname-level rules used to double-check a candidate URL before it enters
# the public health check (defense in depth on top of the strict patterns).
_TUNNEL_HOSTNAME_RULES = {
    "pinggy": [
        r"[a-z0-9][a-z0-9-]*\.a\.free\.pinggy\.link",
        r"[a-z0-9][a-z0-9-]*\.a\.pinggy\.link",
        r"[a-z0-9][a-z0-9-]*\.free\.pinggy\.net",
        r"[a-z0-9][a-z0-9-]*\.pinggy-free\.link",
        r"[a-z0-9][a-z0-9-]*\.a\.free\.pinggy\.online",
    ],
    "cloudflare": [
        r"[a-z0-9][a-z0-9-]*\.trycloudflare\.com",
    ],
    "localhost-run": [
        r"[a-z0-9][a-z0-9-]*\.lhr\.life",
        r"[a-z0-9][a-z0-9-]*\.lhr\.rocks",
    ],
}

# Output markers that mean the tunnel needs interactive auth. In non-PTY
# mode these fail fast; in PTY mode the password prompt is auto-answered
# with an empty line (Pinggy / localhost.run anonymous tunnels accept it).
_AUTH_PROMPT_MARKERS = (
    "password:",
    "Password:",
    "passphrase",
    "Enter passphrase",
)

# Output markers that mean the connection itself failed — always fatal.
_AUTH_FAIL_MARKERS = (
    "Host key verification failed",
    "Permission denied",
)

# Matches an SSH password prompt so the PTY reader can answer it.
_PASSWORD_PROMPT_RE = re.compile(r"(?i)password\s*[:?]")

# Startup grace period for a public URL to become reachable. Cloudflare
# quick tunnels print their URL before the edge is ready, so a single probe
# is not enough — retry until the endpoint answers or the window expires.
PUBLIC_URL_GRACE = 25.0
PUBLIC_URL_RETRY_INTERVAL = 1.5


@dataclass
class TunnelResult:
    provider: str
    url: str = ""
    process: Optional[subprocess.Popen] = None
    error: str = ""


class TunnelProvider(ABC):
    name: str = ""

    @abstractmethod
    def available(self) -> bool:
        """True when the provider's binary is installed."""

    @abstractmethod
    def start(self, port: int, timeout: int) -> TunnelResult:
        """Start the tunnel and return the public URL (or an error)."""


def _extract_https_url(text: str, patterns: List[str]) -> Optional[str]:
    """Return the first HTTPS URL in `text` that matches any pattern.

    Iterates every https:// URL in order so a non-tunnel URL printed first
    (e.g. a Pinggy dashboard/upgrade link) is skipped in favor of the real
    tunnel URL that follows.
    """
    for m in re.finditer(r"https://[^\s\"'<>]+", text):
        url = m.group(0).rstrip("/.,;:)]}")
        for pat in patterns:
            if re.search(pat, url):
                return url
    return None


def _is_valid_tunnel_url(provider: str, url: str) -> bool:
    """True when `url` is a real tunnel URL for `provider`.

    Rejects dashboard/management pages (e.g. dashboard.pinggy.io) and any
    hostname that does not match the provider's tunnel domain rules. Used
    before the public health check so a bad candidate never gets probed.
    """
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return False
    return any(
        re.fullmatch(pat, host) for pat in _TUNNEL_HOSTNAME_RULES.get(provider, [])
    )


def _spawn_pty(cmd: List[str]):
    """Spawn a subprocess attached to a PTY (POSIX only).

    SSH needs a terminal to prompt for a password; Pinggy and localhost.run
    anonymous tunnels accept an empty password. The reader thread answers
    the prompt automatically so the launcher never blocks on human input.
    Returns (proc, master_fd).
    """
    import pty

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave_fd)
    return proc, master_fd


def _read_pty_output(master_fd: int, out_q: "queue.Queue[str]", log_f) -> None:
    """Read PTY output, persist it, and auto-answer password prompts.

    An SSH password prompt is answered with an empty line (the anonymous
    tunnels accept it), so the process never waits for human input. The
    response is capped so a server that keeps re-prompting cannot loop.
    """
    buf = ""
    responses = 0
    while True:
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        text = data.decode("utf-8", errors="replace")
        buf += text
        out_q.put(text)
        log_f.write(text)
        log_f.flush()
        if responses < 3 and _PASSWORD_PROMPT_RE.search(buf):
            buf = ""
            responses += 1
            try:
                os.write(master_fd, b"\n")
            except OSError:
                pass


def _run_and_wait_for_url(
    provider: str,
    cmd: List[str],
    patterns: List[str],
    timeout: int,
    pty: bool = False,
) -> TunnelResult:
    """Run a tunnel command, watch its output for a public URL.

    Output is read on a background thread into a queue so the timeout is
    always honored even if the tunnel process goes completely silent
    (e.g. cloudflared stuck in precheck). Every line is also appended to
    the tunnel log (~/.local/state/termux-mcp/tunnel.log) so failures can
    be diagnosed later.

    With `pty=True` (POSIX) the child runs on a pseudo-terminal: SSH can
    prompt for a password and the reader answers it with an empty line, so
    Pinggy/localhost.run anonymous tunnels authenticate without ever
    blocking on human input. Without a PTY, stdin is /dev/null and any
    auth prompt fails fast.
    """
    log_path = process.TUNNEL_LOG_FILE
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    use_pty = pty and os.name == "posix"

    if use_pty:
        proc, master_fd = _spawn_pty(cmd)
    else:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            env=os.environ.copy(),
        )

    out_q: "queue.Queue[str]" = queue.Queue()

    def _reader() -> None:
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as log_f:
                if use_pty:
                    _read_pty_output(master_fd, out_q, log_f)
                else:
                    for line in proc.stdout:
                        out_q.put(line)
                        log_f.write(line)
                        log_f.flush()
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()

    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = ""
            while True:
                try:
                    tail += out_q.get_nowait()
                except queue.Empty:
                    break
            return TunnelResult(
                provider=provider,
                process=proc,
                error=f"exited early (code {proc.returncode}): {tail[-300:]}",
            )
        try:
            chunk = out_q.get(timeout=0.2)
        except queue.Empty:
            continue
        buf += chunk
        if any(marker in buf for marker in _AUTH_FAIL_MARKERS):
            _terminate(proc)
            return TunnelResult(
                provider=provider,
                process=None,
                error=f"auth/connection failed: {buf.strip()[-120:]}",
            )
        if not use_pty and any(marker in buf for marker in _AUTH_PROMPT_MARKERS):
            _terminate(proc)
            return TunnelResult(
                provider=provider,
                process=None,
                error=f"interactive auth required: {buf.strip()[-120:]}",
            )
        url = _extract_https_url(buf, patterns)
        if url:
            return TunnelResult(provider=provider, url=url, process=proc)
    _terminate(proc)
    return TunnelResult(
        provider=provider,
        process=None,
        error=f"timeout after {timeout}s (no public URL)",
    )


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _pinggy_cmd(port: int) -> List[str]:
    """SSH argv for Pinggy, matching the on-device verified command:
    `ssh -p 443 -o StrictHostKeyChecking=no -o ServerAliveInterval=30
    -R0:127.0.0.1:<port> a@free.pinggy.io` plus non-interactive hardening.

    No BatchMode: Pinggy's anonymous tunnel answers the password prompt
    with an empty password, which the PTY reader supplies automatically.
    """
    return [
        "ssh", "-p", "443",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=15",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "NumberOfPasswordPrompts=1",
        "-R", f"0:127.0.0.1:{port}",
        "a@free.pinggy.io",
    ]


def _localhost_run_cmd(port: int) -> List[str]:
    """SSH argv for localhost.run (same anonymous-tunnel password handling)."""
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ConnectTimeout=15",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "NumberOfPasswordPrompts=1",
        "-R", f"80:127.0.0.1:{port}",
        "nokey@localhost.run",
    ]


class PinggyProvider(TunnelProvider):
    name = "pinggy"

    def available(self) -> bool:
        return shutil.which("ssh") is not None

    def start(self, port: int, timeout: int) -> TunnelResult:
        return _run_and_wait_for_url(
            self.name, _pinggy_cmd(port), _URL_PATTERNS[self.name], timeout, pty=True
        )


class CloudflareProvider(TunnelProvider):
    name = "cloudflare"

    def available(self) -> bool:
        return shutil.which("cloudflared") is not None

    def start(self, port: int, timeout: int) -> TunnelResult:
        cmd = ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"]
        return _run_and_wait_for_url(self.name, cmd, _URL_PATTERNS[self.name], timeout)


class LocalhostRunProvider(TunnelProvider):
    name = "localhost-run"

    def available(self) -> bool:
        return shutil.which("ssh") is not None

    def start(self, port: int, timeout: int) -> TunnelResult:
        return _run_and_wait_for_url(
            self.name,
            _localhost_run_cmd(port),
            _URL_PATTERNS[self.name],
            timeout,
            pty=True,
        )


_PROVIDERS = {
    "pinggy": PinggyProvider,
    "cloudflare": CloudflareProvider,
    "localhost-run": LocalhostRunProvider,
}


def get_provider(name: str) -> Optional[TunnelProvider]:
    cls = _PROVIDERS.get(name)
    return cls() if cls else None


def start_tunnel(
    port: int,
    provider: str = "auto",
    timeout: Optional[int] = None,
) -> TunnelResult:
    """Start a tunnel and return the first public URL.

    `provider="auto"` tries each configured provider in order
    (TERMUX_MCP_TUNNEL_PROVIDERS), skipping unavailable ones and falling
    back on timeout/failure. A provider only counts as successful once its
    public URL is actually reachable (see wait_for_public_url) — a parsed
    URL that never answers (e.g. Cloudflare 530) is treated as a failure
    and the provider is terminated.
    """
    timeout = timeout or TUNNEL_TIMEOUT
    last_error = ""
    if provider == "auto":
        for name in TUNNEL_PROVIDERS:
            p = get_provider(name)
            if p is None or not p.available():
                continue
            result = p.start(port, timeout)
            if result.url:
                if not _is_valid_tunnel_url(name, result.url):
                    last_error = (
                        f"{name}: URL does not match tunnel hostname rules: "
                        f"{result.url}"
                    )
                    if result.process:
                        _terminate(result.process)
                    continue
                if wait_for_public_url(result.url, result.process):
                    return result
                if result.process and result.process.poll() is not None:
                    last_error = (
                        f"{name}: tunnel exited during startup "
                        f"(code {result.process.returncode})"
                    )
                else:
                    last_error = (
                        f"{name}: public URL not reachable within "
                        f"{PUBLIC_URL_GRACE:.0f}s: {result.url}"
                    )
                if result.process:
                    _terminate(result.process)
                continue
            last_error = f"{name}: {result.error}"
        return TunnelResult(
            provider="auto",
            error=f"all configured providers failed: {last_error}",
        )
    p = get_provider(provider)
    if p is None:
        return TunnelResult(provider=provider, error=f"unknown provider: {provider}")
    if not p.available():
        return TunnelResult(
            provider=provider,
            error=f"{provider} is not installed (install ssh/cloudflared)",
        )
    result = p.start(port, timeout)
    if result.url:
        if not _is_valid_tunnel_url(provider, result.url):
            if result.process:
                _terminate(result.process)
            return TunnelResult(
                provider=provider,
                error=(
                    f"URL does not match tunnel hostname rules: {result.url}"
                ),
            )
        if wait_for_public_url(result.url, result.process):
            return result
        if result.process and result.process.poll() is not None:
            return TunnelResult(
                provider=provider,
                error=f"tunnel exited during startup (code {result.process.returncode})",
            )
        if result.process:
            _terminate(result.process)
        return TunnelResult(
            provider=provider,
            error=(
                f"public URL not reachable within {PUBLIC_URL_GRACE:.0f}s: "
                f"{result.url}"
            ),
        )
    return result


def wait_for_public_url(
    url: str,
    proc: Optional[subprocess.Popen],
    total_wait: float = PUBLIC_URL_GRACE,
    interval: float = PUBLIC_URL_RETRY_INTERVAL,
) -> bool:
    """Wait until the public URL answers, with a startup grace period.

    A parsed URL is not proof the tunnel works: Cloudflare quick tunnels
    print their URL before the edge is reachable. Retry every `interval`
    seconds until the endpoint answers (the MCP server's 401 + JSON body —
    auth working as intended) or `total_wait` expires. If the tunnel
    process exits while we wait, fail immediately so the caller can report
    the exit code.
    """
    deadline = time.time() + total_wait
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if verify_url(url, timeout=5.0):
            return True
        time.sleep(interval)
    return False


def _looks_like_mcp_unauthorized(body: str) -> bool:
    """True when the body matches the MCP server's 401 response.

    The MCP endpoint returns `{"error": "Unauthorized"}` (JSON) when probed
    without an Authorization header. Requiring this JSON structure avoids
    false positives from third-party pages that happen to return 401.
    """
    try:
        data = json.loads(body)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("error") == "Unauthorized"


def verify_url(url: str, timeout: float = 15.0) -> bool:
    """Check that a public URL is the Termux-MCP endpoint.

    Probes `{url}/mcp` without any Authorization header. Only the expected
    unauthorized response from the MCP server counts as healthy: HTTP 401
    with a JSON body like `{"error": "Unauthorized"}`. Anything else — 200
    dashboard HTML, 301 redirects, 403/404 third-party pages, 502/530 — is
    NOT the MCP endpoint and counts as unreachable.
    """
    probe = url.rstrip("/")
    if not probe.endswith("/mcp"):
        probe += "/mcp"
    try:
        req = urllib.request.Request(probe, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return False  # 200 from a tunnel is not the MCP endpoint
    except urllib.error.HTTPError as e:
        if e.code != 401:
            return False
        body = ""
        try:
            body = e.read(2048).decode("utf-8", errors="replace")
        except Exception:
            pass
        return _looks_like_mcp_unauthorized(body)
    except Exception:
        return False