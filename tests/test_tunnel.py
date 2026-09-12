"""Tests for tunnel provider selection, URL parsing, and auto fallback.

These are pure unit tests — no real network or tunnel binaries are used.
Real tunnel connectivity is covered by the optional integration smoke test
(scripts/mcp_smoke.py) and manual `termux-mcp start --tunnel ...`.
"""

import io
import os
import subprocess
import sys
import time
import urllib.error

import pytest

from termux_mcp import tunnel


# ── HTTPS URL parsing ────────────────────────────────────────────────────────

def test_extract_https_url_pinggy():
    text = "Forwarding traffic... https://abc123.a.free.pinggy.link"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["pinggy"])
    assert url == "https://abc123.a.free.pinggy.link"


def test_extract_https_url_pinggy_io():
    text = "https://abc123.pinggy.io is live"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["pinggy"])
    assert url is None  # pinggy.io is the official domain, not a tunnel


def test_extract_https_url_picks_tunnel_over_dashboard():
    """Pinggy prints dashboard/upgrade links before the real tunnel URL —
    the parser must skip them and pick the actual tunnel hostname."""
    text = (
        "Dashboard: https://dashboard.pinggy.io\n"
        "Upgrade: https://pinggy.io/pricing\n"
        "Tunnel: https://abc123.a.free.pinggy.link"
    )
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["pinggy"])
    assert url == "https://abc123.a.free.pinggy.link"


def test_extract_https_url_free_pinggy_net():
    text = "https://abc123.free.pinggy.net is live"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["pinggy"])
    assert url == "https://abc123.free.pinggy.net"


def test_extract_https_url_pinggy_free_link():
    text = "https://abc123.pinggy-free.link is live"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["pinggy"])
    assert url == "https://abc123.pinggy-free.link"


def test_is_valid_tunnel_url():
    assert tunnel._is_valid_tunnel_url(
        "pinggy", "https://abc123.a.free.pinggy.link"
    ) is True
    assert tunnel._is_valid_tunnel_url(
        "pinggy", "https://abc123.free.pinggy.net"
    ) is True
    assert tunnel._is_valid_tunnel_url(
        "pinggy", "https://abc123.pinggy-free.link"
    ) is True
    assert tunnel._is_valid_tunnel_url("pinggy", "https://dashboard.pinggy.io") is False
    assert tunnel._is_valid_tunnel_url("pinggy", "https://pinggy.io") is False
    assert tunnel._is_valid_tunnel_url(
        "cloudflare", "https://abc-123.trycloudflare.com"
    ) is True
    assert tunnel._is_valid_tunnel_url(
        "localhost-run", "https://abc.lhr.life"
    ) is True


def test_extract_https_url_cloudflare():
    text = "Your quick Tunnel has been created! Visit it at https://abc-123.trycloudflare.com"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["cloudflare"])
    assert url == "https://abc-123.trycloudflare.com"


def test_extract_https_url_localhost_run():
    text = "https://abc.lhr.life forwarded to localhost:8765"
    url = tunnel._extract_https_url(text, tunnel._URL_PATTERNS["localhost-run"])
    assert url == "https://abc.lhr.life"


def test_extract_https_url_no_match():
    assert tunnel._extract_https_url("no url here", tunnel._URL_PATTERNS["pinggy"]) is None


# ── Provider selection ───────────────────────────────────────────────────────

def test_get_provider():
    assert tunnel.get_provider("pinggy").name == "pinggy"
    assert tunnel.get_provider("cloudflare").name == "cloudflare"
    assert tunnel.get_provider("localhost-run").name == "localhost-run"
    assert tunnel.get_provider("unknown") is None


def test_start_tunnel_unknown_provider():
    result = tunnel.start_tunnel(8765, provider="unknown", timeout=1)
    assert result.url == ""
    assert "unknown" in result.error


def test_start_tunnel_provider_not_available(monkeypatch):
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return False

        def start(self, port, timeout):
            raise AssertionError("start must not be called when unavailable")

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    assert result.url == ""
    assert "not installed" in result.error


# ── Auto fallback ────────────────────────────────────────────────────────────

def test_start_tunnel_auto_fallback(monkeypatch):
    """First provider times out, second succeeds — auto picks the second."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(provider="pinggy", error="timeout after 1s")

    class FakeCloudflare:
        name = "cloudflare"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="cloudflare", url="https://x.trycloudflare.com"
            )

    monkeypatch.setattr(
        tunnel, "_PROVIDERS", {"pinggy": FakePinggy, "cloudflare": FakeCloudflare}
    )
    monkeypatch.setattr(tunnel, "TUNNEL_PROVIDERS", ["pinggy", "cloudflare"])
    monkeypatch.setattr(tunnel, "wait_for_public_url", lambda url, proc: True)
    result = tunnel.start_tunnel(8765, provider="auto", timeout=1)
    assert result.url == "https://x.trycloudflare.com"
    assert result.provider == "cloudflare"


def test_start_tunnel_auto_fallback_on_unreachable_url(monkeypatch):
    """First provider returns a URL that is NOT reachable — auto falls back."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="pinggy", url="https://dead.a.free.pinggy.link"
            )

    class FakeCloudflare:
        name = "cloudflare"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="cloudflare", url="https://x.trycloudflare.com"
            )

    monkeypatch.setattr(
        tunnel, "_PROVIDERS", {"pinggy": FakePinggy, "cloudflare": FakeCloudflare}
    )
    monkeypatch.setattr(tunnel, "TUNNEL_PROVIDERS", ["pinggy", "cloudflare"])
    monkeypatch.setattr(
        tunnel, "wait_for_public_url",
        lambda url, proc: url.startswith("https://x.trycloudflare.com"),
    )
    result = tunnel.start_tunnel(8765, provider="auto", timeout=1)
    assert result.url == "https://x.trycloudflare.com"
    assert result.provider == "cloudflare"


def test_start_tunnel_single_provider_unreachable_url(monkeypatch):
    """A single provider whose URL is unreachable must report failure."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="pinggy", url="https://dead.a.free.pinggy.link"
            )

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    monkeypatch.setattr(tunnel, "wait_for_public_url", lambda url, proc: False)
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    assert result.url == ""
    assert "not reachable" in result.error


def test_start_tunnel_auto_all_fail(monkeypatch):
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(provider="pinggy", error="timeout")

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    monkeypatch.setattr(tunnel, "TUNNEL_PROVIDERS", ["pinggy"])
    result = tunnel.start_tunnel(8765, provider="auto", timeout=1)
    assert result.url == ""
    assert "all configured providers failed" in result.error


def test_start_tunnel_auto_skips_unavailable(monkeypatch):
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return False

        def start(self, port, timeout):
            raise AssertionError("unavailable provider must be skipped")

    class FakeCloudflare:
        name = "cloudflare"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="cloudflare", url="https://x.trycloudflare.com"
            )

    monkeypatch.setattr(
        tunnel, "_PROVIDERS", {"pinggy": FakePinggy, "cloudflare": FakeCloudflare}
    )
    monkeypatch.setattr(tunnel, "TUNNEL_PROVIDERS", ["pinggy", "cloudflare"])
    monkeypatch.setattr(tunnel, "wait_for_public_url", lambda url, proc: True)
    result = tunnel.start_tunnel(8765, provider="auto", timeout=1)
    assert result.url == "https://x.trycloudflare.com"


def test_start_tunnel_rejects_non_tunnel_url(monkeypatch):
    """A provider returning a dashboard/management URL must be rejected
    BEFORE any health check runs."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            return tunnel.TunnelResult(
                provider="pinggy", url="https://dashboard.pinggy.io"
            )

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    # If the URL were probed, this would return True — it must never be called.
    monkeypatch.setattr(tunnel, "wait_for_public_url", lambda url, proc: True)
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    assert result.url == ""
    assert "hostname rules" in result.error


# ── URL verification ─────────────────────────────────────────────────────────

def _http_error(code, body=b""):
    """Build an HTTPError whose body can be read (like a real urlopen 4xx)."""
    return urllib.error.HTTPError(
        "https://x/mcp", code, "err", {}, io.BytesIO(body)
    )


def test_verify_url_401_counts_reachable(monkeypatch):
    """401 with the MCP JSON body (auth working) must count as reachable."""
    def fake_urlopen(req, timeout):
        raise _http_error(401, b'{"error": "Unauthorized"}')

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is True


def test_verify_url_401_wrong_body_fails(monkeypatch):
    """A third-party 401 (non-MCP body) must NOT count as reachable."""
    def fake_urlopen(req, timeout):
        raise _http_error(401, b"<html>Unauthorized</html>")

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is False


def test_verify_url_200_not_mcp_fails(monkeypatch):
    """200 (dashboard/app HTML) must NOT count as the MCP endpoint."""
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        return FakeResp()

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is False


def test_verify_url_404_dashboard_fails(monkeypatch):
    """404 (e.g. Pinggy dashboard /mcp) must NOT count as reachable."""
    def fake_urlopen(req, timeout):
        raise _http_error(404, b"<html>Not Found</html>")

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://dashboard.pinggy.io") is False


def test_verify_url_301_redirect_fails(monkeypatch):
    """301 redirect to the official site must NOT count as reachable."""
    def fake_urlopen(req, timeout):
        raise _http_error(301, b"")

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is False


def test_verify_url_unreachable(monkeypatch):
    def fake_urlopen(req, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is False


def test_verify_url_probes_mcp_endpoint(monkeypatch):
    """Health probe must hit {url}/mcp without any Authorization header."""
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        raise _http_error(401, b'{"error": "Unauthorized"}')

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is True
    assert seen["url"] == "https://x.trycloudflare.com/mcp"
    assert seen["auth"] is None


def test_verify_url_530_unreachable(monkeypatch):
    """Cloudflare 530 (origin unreachable) must count as unreachable."""
    def fake_urlopen(req, timeout):
        raise _http_error(530, b"")

    monkeypatch.setattr(tunnel.urllib.request, "urlopen", fake_urlopen)
    assert tunnel.verify_url("https://x.trycloudflare.com") is False


# ── Provider command construction ────────────────────────────────────────────

def test_pinggy_cmd_full_argv():
    """Pinggy argv must match the on-device verified command: port 443, no
    BatchMode (the anonymous tunnel needs the password prompt answered),
    non-interactive hardening, and the 127.0.0.1 reverse forward."""
    cmd = tunnel._pinggy_cmd(8765)
    assert cmd[0] == "ssh"
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "443"
    assert "BatchMode=yes" not in cmd
    opts = cmd[cmd.index("-o") + 1 : cmd.index("-R")]
    assert "StrictHostKeyChecking=no" in opts
    assert "ServerAliveInterval=30" in opts
    assert "ConnectTimeout=15" in opts
    assert "ExitOnForwardFailure=yes" in opts
    assert "NumberOfPasswordPrompts=1" in opts
    assert "0:127.0.0.1:8765" in cmd
    assert "a@free.pinggy.io" in cmd


def test_pinggy_start_uses_pty_and_generated_cmd(monkeypatch):
    """Pinggy must run on a PTY (so the password prompt can be answered)."""
    captured = {}

    def fake_run(provider, cmd, patterns, timeout, pty=False):
        captured["cmd"] = cmd
        captured["pty"] = pty
        return tunnel.TunnelResult(provider=provider, url="https://x.a.free.pinggy.link")

    monkeypatch.setattr(tunnel, "_run_and_wait_for_url", fake_run)
    result = tunnel.get_provider("pinggy").start(8765, timeout=10)
    assert result.url == "https://x.a.free.pinggy.link"
    assert captured["pty"] is True
    assert captured["cmd"] == tunnel._pinggy_cmd(8765)


def test_localhost_run_cmd_full_argv():
    """localhost.run argv must use the same anonymous-tunnel handling."""
    cmd = tunnel._localhost_run_cmd(8765)
    assert cmd[0] == "ssh"
    assert "BatchMode=yes" not in cmd
    assert "StrictHostKeyChecking=no" in cmd
    assert "NumberOfPasswordPrompts=1" in cmd
    assert "80:127.0.0.1:8765" in cmd
    assert "nokey@localhost.run" in cmd


def test_localhost_run_start_uses_pty(monkeypatch):
    captured = {}

    def fake_run(provider, cmd, patterns, timeout, pty=False):
        captured["pty"] = pty
        return tunnel.TunnelResult(provider=provider, url="https://x.lhr.life")

    monkeypatch.setattr(tunnel, "_run_and_wait_for_url", fake_run)
    result = tunnel.get_provider("localhost-run").start(8765, timeout=10)
    assert result.url == "https://x.lhr.life"
    assert captured["pty"] is True


# ── Real subprocess + tunnel log ─────────────────────────────────────────────

def test_run_and_wait_writes_tunnel_log_and_returns_process(tmp_path, monkeypatch):
    """A real subprocess that prints a URL must: return the URL, keep the
    process alive, and persist its output to tunnel.log."""
    from termux_mcp import process as proc_mod

    monkeypatch.setattr(proc_mod, "TUNNEL_LOG_FILE", str(tmp_path / "tunnel.log"))
    # A tiny python child that prints a pinggy URL then sleeps.
    code = (
        "import sys,time;"
        "print('Forwarding traffic... https://abc123.a.free.pinggy.link');"
        "sys.stdout.flush();time.sleep(30)"
    )
    result = tunnel._run_and_wait_for_url(
        "pinggy",
        [sys.executable, "-c", code],
        tunnel._URL_PATTERNS["pinggy"],
        timeout=10,
    )
    try:
        assert result.url == "https://abc123.a.free.pinggy.link"
        assert result.process is not None
        assert result.process.poll() is None  # still alive
        # tunnel.log must contain the child's output.
        log = (tmp_path / "tunnel.log").read_text(encoding="utf-8", errors="replace")
        assert "abc123.a.free.pinggy.link" in log
    finally:
        if result.process:
            tunnel._terminate(result.process)


def test_run_and_wait_auth_prompt_fails_fast(tmp_path, monkeypatch):
    """An SSH password prompt must fail fast (never block until timeout)."""
    from termux_mcp import process as proc_mod

    monkeypatch.setattr(proc_mod, "TUNNEL_LOG_FILE", str(tmp_path / "tunnel.log"))
    code = (
        "import sys,time;"
        "print(\"a@free.pinggy.io's password:\");"
        "sys.stdout.flush();time.sleep(30)"
    )
    t0 = time.time()
    result = tunnel._run_and_wait_for_url(
        "pinggy",
        [sys.executable, "-c", code],
        tunnel._URL_PATTERNS["pinggy"],
        timeout=30,
    )
    elapsed = time.time() - t0
    assert result.url == ""
    assert "interactive auth required" in result.error
    assert elapsed < 10  # must not wait for the full timeout


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only")
def test_run_and_wait_pty_auto_responds_password(tmp_path, monkeypatch):
    """In PTY mode a password prompt must be auto-answered with an empty
    password and the tunnel must proceed to print its URL."""
    from termux_mcp import process as proc_mod

    monkeypatch.setattr(proc_mod, "TUNNEL_LOG_FILE", str(tmp_path / "tunnel.log"))
    code = (
        "import sys,time;"
        "print(\"a@free.pinggy.io's password:\", end='', flush=True);"
        "sys.stdin.readline();"
        "print('Forwarding traffic... https://abc123.a.free.pinggy.link');"
        "sys.stdout.flush();time.sleep(30)"
    )
    result = tunnel._run_and_wait_for_url(
        "pinggy",
        [sys.executable, "-c", code],
        tunnel._URL_PATTERNS["pinggy"],
        timeout=10,
        pty=True,
    )
    try:
        assert result.url == "https://abc123.a.free.pinggy.link"
        assert result.process is not None
        assert result.process.poll() is None  # still alive
    finally:
        if result.process:
            tunnel._terminate(result.process)


# ── Public URL startup grace period ──────────────────────────────────────────

class _FakeProc:
    """Minimal stand-in for a subprocess.Popen: poll() returns the exit
    code once the process has 'died' (None while it is alive)."""

    def __init__(self, exit_code=None):
        self._exit = exit_code

    def poll(self):
        return self._exit


def test_wait_for_public_url_retries_until_reachable(monkeypatch):
    """A URL that needs a few seconds to become reachable must be retried,
    not failed on the first probe."""
    calls = {"n": 0}

    def flaky(url, timeout=5.0):
        calls["n"] += 1
        return calls["n"] >= 3

    monkeypatch.setattr(tunnel, "verify_url", flaky)
    proc = _FakeProc()  # stays alive
    assert tunnel.wait_for_public_url(
        "https://x.trycloudflare.com", proc, total_wait=5.0, interval=0.01
    ) is True
    assert calls["n"] >= 3


def test_wait_for_public_url_process_exit_fails_fast(monkeypatch):
    """If the tunnel process exits while waiting, fail immediately."""
    monkeypatch.setattr(tunnel, "verify_url", lambda url, timeout=5.0: False)
    proc = _FakeProc(exit_code=1)  # already dead
    t0 = time.time()
    assert tunnel.wait_for_public_url(
        "https://x.trycloudflare.com", proc, total_wait=30.0, interval=0.01
    ) is False
    assert time.time() - t0 < 5


def test_wait_for_public_url_grace_exhausted(monkeypatch):
    """If the URL never answers, fail once the grace window expires."""
    monkeypatch.setattr(tunnel, "verify_url", lambda url, timeout=5.0: False)
    proc = _FakeProc()
    t0 = time.time()
    assert tunnel.wait_for_public_url(
        "https://x.trycloudflare.com", proc, total_wait=0.3, interval=0.05
    ) is False
    assert time.time() - t0 < 5


def test_start_tunnel_waits_for_url_grace_period(monkeypatch):
    """A provider whose URL becomes reachable after a few probes must NOT be
    killed — start_tunnel waits through the grace period and keeps it."""
    calls = {"n": 0}

    def flaky(url, timeout=5.0):
        calls["n"] += 1
        return calls["n"] >= 3

    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            return tunnel.TunnelResult(
                provider="pinggy", url="https://x.a.free.pinggy.link", process=proc
            )

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    monkeypatch.setattr(tunnel, "verify_url", flaky)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_GRACE", 5.0)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_RETRY_INTERVAL", 0.05)
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    try:
        assert result.url == "https://x.a.free.pinggy.link"
        assert result.process is not None
        assert result.process.poll() is None  # NOT killed
        assert calls["n"] >= 3
    finally:
        if result.process:
            tunnel._terminate(result.process)


def test_start_tunnel_kills_provider_after_grace_exhausted(monkeypatch):
    """If the URL never becomes reachable, the provider must be terminated
    and start_tunnel must report failure."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            return tunnel.TunnelResult(
                provider="pinggy", url="https://dead.a.free.pinggy.link", process=proc
            )

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    monkeypatch.setattr(tunnel, "verify_url", lambda url, timeout=5.0: False)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_GRACE", 0.3)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_RETRY_INTERVAL", 0.05)
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    assert result.url == ""
    assert "not reachable" in result.error


def test_start_tunnel_fails_fast_when_tunnel_exits_during_grace(monkeypatch):
    """If the tunnel process exits while waiting for the URL, fail
    immediately and report the exit code."""
    class FakePinggy:
        name = "pinggy"

        def available(self):
            return True

        def start(self, port, timeout):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(3)"]
            )
            return tunnel.TunnelResult(
                provider="pinggy", url="https://dead.a.free.pinggy.link", process=proc
            )

    monkeypatch.setattr(tunnel, "_PROVIDERS", {"pinggy": FakePinggy})
    monkeypatch.setattr(tunnel, "verify_url", lambda url, timeout=5.0: False)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_GRACE", 30.0)
    monkeypatch.setattr(tunnel, "PUBLIC_URL_RETRY_INTERVAL", 0.05)
    result = tunnel.start_tunnel(8765, provider="pinggy", timeout=1)
    assert result.url == ""
    assert "exited" in result.error