"""Tests for OAuth / auth-discovery support.

Covers: static Bearer compatibility, RFC 9728 protected-resource metadata,
the WWW-Authenticate challenge, public-URL safety (no Host-header trust),
provider coexistence, and the full authorization-code + PKCE flow against
the self-hosted authorization server.
"""

import asyncio
import base64
import hashlib
import json
import os
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import uvicorn

from termux_mcp import config, oauth
from termux_mcp.auth import (
    AuthResult,
    BearerAuthProvider,
    CompositeAuthProvider,
    OAuthAuthProvider,
    get_auth_provider,
    reset_auth_provider,
)
from termux_mcp.config import AUTH_TOKEN
from termux_mcp.mcp_server import _build_mcp_app

SCOPES = ["mcp:read", "mcp:write"]
ISSUER = "https://mcp.example.com"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server(app):
    """Run a Starlette app on a free port; return (server, thread, base_url)."""
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(base + "/mcp", timeout=0.3)
            break
        except Exception:
            time.sleep(0.1)
    return server, thread, base


def _stop_server(server, thread):
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def oauth_config(monkeypatch):
    """Enable OAuth with a stable public URL + issuer."""
    monkeypatch.setattr(config, "OAUTH_ISSUER", ISSUER)
    monkeypatch.setattr(config, "PUBLIC_URL", ISSUER)
    monkeypatch.setattr(config, "OAUTH_SCOPES", " ".join(SCOPES))
    config.clear_public_url()
    reset_auth_provider()
    oauth.reset_auth_server_provider()
    yield
    config.clear_public_url()
    reset_auth_provider()
    oauth.reset_auth_server_provider()


# ── Static Bearer compatibility ──────────────────────────────────────────────

def test_bearer_auth_provider_compat():
    p = BearerAuthProvider("secret-token", required=True)
    assert p.enabled is True
    assert p.authenticate({"Authorization": "Bearer secret-token"}) is True
    assert p.authenticate({"Authorization": "Bearer wrong-token"}) is False
    assert p.authenticate({}) is False
    assert p.authenticate({"Authorization": "Basic abc"}) is False
    # Query-string tokens are never accepted (no such path exists).
    assert p.authenticate({"Authorization": ""}) is False


def test_bearer_auth_provider_not_required():
    p = BearerAuthProvider("", required=False)
    assert p.enabled is False
    assert p.authenticate({}) is True


def test_auth_result_shape():
    r = AuthResult(authorized=True, scopes=["mcp:read"], client_id="c", subject="s")
    assert r.authorized is True
    assert r.scopes == ["mcp:read"]
    assert r.client_id == "c"
    assert r.subject == "s"


def test_static_bearer_still_works_with_oauth_enabled(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        # configured static token succeeds
        r = httpx.post(
            base + "/mcp", json={},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert r.status_code != 401
        # missing token => 401
        r = httpx.post(base + "/mcp", json={})
        assert r.status_code == 401
        # wrong token => 401
        r = httpx.post(
            base + "/mcp", json={},
            headers={"Authorization": "Bearer wrong-token-0000000000000000"},
        )
        assert r.status_code == 401
        # query-string token is rejected
        r = httpx.post(f"{base}/mcp?token={AUTH_TOKEN}", json={})
        assert r.status_code == 401
    finally:
        _stop_server(server, thread)


# ── OAuth discovery (RFC 9728 protected resource metadata) ──────────────────

def test_protected_resource_metadata(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        r = httpx.get(base + "/.well-known/oauth-protected-resource/mcp")
        assert r.status_code == 200
        data = r.json()
        assert data["resource"] == f"{ISSUER}/mcp"
        # AnyHttpUrl normalizes with a trailing slash; compare normalized.
        assert data["authorization_servers"][0].rstrip("/") == ISSUER
        assert data["scopes_supported"] == SCOPES
        assert data["bearer_methods_supported"] == ["header"]

        # host-form endpoint also exists
        r2 = httpx.get(base + "/.well-known/oauth-protected-resource")
        assert r2.status_code == 200
        assert r2.json()["resource"] == f"{ISSUER}/mcp"
    finally:
        _stop_server(server, thread)


def test_auth_server_metadata(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        r = httpx.get(base + "/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        data = r.json()
        assert data["issuer"].rstrip("/") == ISSUER
        assert data["authorization_endpoint"] == f"{ISSUER}/authorize"
        assert data["token_endpoint"] == f"{ISSUER}/token"
        assert data["registration_endpoint"] == f"{ISSUER}/register"
        assert data["code_challenge_methods_supported"] == ["S256"]
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]
    finally:
        _stop_server(server, thread)


# ── 401 challenge ────────────────────────────────────────────────────────────

def test_401_challenge_includes_resource_metadata(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        r = httpx.post(base + "/mcp", json={})
        assert r.status_code == 401
        www = r.headers.get("www-authenticate", "")
        assert www.startswith("Bearer")
        assert "resource_metadata=" in www
        assert f"{ISSUER}/.well-known/oauth-protected-resource/mcp" in www
        assert "scope=" in www
        assert "mcp:read" in www and "mcp:write" in www
    finally:
        _stop_server(server, thread)


def test_no_oauth_discovery_when_disabled():
    # OAuth disabled (default config): plain Bearer challenge, no discovery.
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        r = httpx.post(base + "/mcp", json={})
        assert r.status_code == 401
        www = r.headers.get("www-authenticate", "")
        assert www == "Bearer"
        assert "resource_metadata" not in www
        # discovery route is not advertised (auth required => 401, not 200)
        r2 = httpx.get(base + "/.well-known/oauth-protected-resource/mcp")
        assert r2.status_code == 401
    finally:
        _stop_server(server, thread)


# ── Public URL safety ────────────────────────────────────────────────────────

def test_metadata_ignores_host_headers(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        r = httpx.get(
            base + "/.well-known/oauth-protected-resource/mcp",
            headers={
                "X-Forwarded-Host": "evil.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "203.0.113.9",
            },
        )
        data = r.json()
        # configured public URL wins; forwarded headers are ignored
        assert data["resource"] == f"{ISSUER}/mcp"
        assert "evil.example.com" not in data["resource"]
        assert "127.0.0.1" not in data["resource"]
    finally:
        _stop_server(server, thread)


def test_runtime_public_url_takes_priority(oauth_config):
    # Runtime URL (written by the tunnel manager) overrides configured URL.
    config.set_public_url("https://tunnel.example.com")
    try:
        app = _build_mcp_app()
        server, thread, base = _start_server(app)
        try:
            r = httpx.get(base + "/.well-known/oauth-protected-resource/mcp")
            assert r.json()["resource"] == "https://tunnel.example.com/mcp"
            r2 = httpx.post(base + "/mcp", json={})
            www = r2.headers.get("www-authenticate", "")
            assert "https://tunnel.example.com/.well-known/oauth-protected-resource/mcp" in www
        finally:
            _stop_server(server, thread)
    finally:
        config.clear_public_url()


def test_auto_issuer_resolves_to_public_url(monkeypatch):
    monkeypatch.setattr(config, "OAUTH_ISSUER", "auto")
    monkeypatch.setattr(config, "PUBLIC_URL", "")
    config.set_public_url("https://tunnel.example.com")
    try:
        assert oauth.get_issuer() == "https://tunnel.example.com"
        assert oauth.get_resource_url() == "https://tunnel.example.com/mcp"
    finally:
        config.clear_public_url()


# ── Provider coexistence ─────────────────────────────────────────────────────

class _FakeVerifier:
    """Minimal TokenVerifier for unit-level provider tests."""

    def __init__(self, valid_token="oauth-token"):
        self._valid = valid_token

    async def verify_token(self, token):
        if token == self._valid:
            from mcp.server.auth.provider import AccessToken
            return AccessToken(
                token=token,
                client_id="test-client",
                scopes=["mcp:read", "mcp:write"],
                expires_at=int(time.time()) + 3600,
            )
        return None


def test_composite_provider_coexist():
    bearer = BearerAuthProvider("static-token", required=True)
    oauth_provider = OAuthAuthProvider(_FakeVerifier(), SCOPES)
    composite = CompositeAuthProvider([bearer, oauth_provider])
    assert composite.enabled is True

    # sync path: static Bearer only
    assert composite.authenticate({"Authorization": "Bearer static-token"}) is True
    assert composite.authenticate({"Authorization": "Bearer oauth-token"}) is False

    # async path: both accepted
    r = asyncio.run(composite.authenticate_async({"Authorization": "Bearer static-token"}))
    assert r.authorized is True
    r = asyncio.run(composite.authenticate_async({"Authorization": "Bearer oauth-token"}))
    assert r.authorized is True
    assert r.scopes == SCOPES
    assert r.client_id == "test-client"
    r = asyncio.run(composite.authenticate_async({"Authorization": "Bearer nope"}))
    assert r.authorized is False


def test_oauth_token_and_static_bearer_coexist_on_mcp(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        provider = oauth.get_auth_server_provider()
        token = asyncio.run(_issue_access_token(provider, SCOPES))

        # OAuth access token accepted
        r = httpx.post(base + "/mcp", json={}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code != 401
        # static Bearer still accepted
        r = httpx.post(base + "/mcp", json={}, headers={"Authorization": f"Bearer {AUTH_TOKEN}"})
        assert r.status_code != 401
        # garbage rejected
        r = httpx.post(base + "/mcp", json={}, headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401
    finally:
        _stop_server(server, thread)


# ── Full authorization-code + PKCE flow ──────────────────────────────────────

async def _issue_access_token(provider, scopes):
    """Register a client and exchange an authorization code for a token."""
    from mcp.server.auth.provider import AuthorizationParams
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyHttpUrl

    client = OAuthClientInformationFull(
        client_id="test-client",
        client_secret="test-secret",
        redirect_uris=[AnyHttpUrl("http://localhost:9999/callback")],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(scopes),
    )
    await provider.register_client(client)
    redirect = await provider.authorize(
        client,
        AuthorizationParams(
            state="test-state",
            scopes=scopes,
            code_challenge="test-challenge",
            redirect_uri=AnyHttpUrl("http://localhost:9999/callback"),
            redirect_uri_provided_explicitly=True,
        ),
    )
    code = parse_qs(urlparse(redirect).query)["code"][0]
    auth_code = await provider.load_authorization_code(client, code)
    token = await provider.exchange_authorization_code(client, auth_code)
    return token.access_token


def test_authorization_code_one_time_use(oauth_config):
    provider = oauth.get_auth_server_provider()

    async def run():
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        client = OAuthClientInformationFull(
            client_id="c1",
            redirect_uris=[AnyHttpUrl("http://localhost:9999/cb")],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(SCOPES),
        )
        await provider.register_client(client)
        redirect = await provider.authorize(
            client,
            AuthorizationParams(
                state="s",
                scopes=SCOPES,
                code_challenge="ch",
                redirect_uri=AnyHttpUrl("http://localhost:9999/cb"),
                redirect_uri_provided_explicitly=True,
            ),
        )
        code = parse_qs(urlparse(redirect).query)["code"][0]
        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None
        await provider.exchange_authorization_code(client, auth_code)
        # one-time use: the code is consumed
        assert await provider.load_authorization_code(client, code) is None

    asyncio.run(run())


def test_refresh_token_rotation(oauth_config):
    provider = oauth.get_auth_server_provider()

    async def run():
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        client = OAuthClientInformationFull(
            client_id="c2",
            redirect_uris=[AnyHttpUrl("http://localhost:9999/cb")],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(SCOPES),
        )
        await provider.register_client(client)
        redirect = await provider.authorize(
            client,
            AuthorizationParams(
                state="s",
                scopes=SCOPES,
                code_challenge="ch",
                redirect_uri=AnyHttpUrl("http://localhost:9999/cb"),
                redirect_uri_provided_explicitly=True,
            ),
        )
        code = parse_qs(urlparse(redirect).query)["code"][0]
        auth_code = await provider.load_authorization_code(client, code)
        tokens = await provider.exchange_authorization_code(client, auth_code)
        refresh = tokens.refresh_token
        assert refresh is not None

        rt = await provider.load_refresh_token(client, refresh)
        assert rt is not None
        new_tokens = await provider.exchange_refresh_token(client, rt, SCOPES)
        # rotation: new refresh token differs, old one is revoked
        assert new_tokens.refresh_token != refresh
        assert await provider.load_refresh_token(client, refresh) is None

    asyncio.run(run())


def test_access_token_expiry(oauth_config):
    provider = oauth.get_auth_server_provider()

    async def run():
        token = await _issue_access_token(provider, SCOPES)
        access = await provider.load_access_token(token)
        assert access is not None
        # simulate expiry
        access.expires_at = int(time.time()) - 1
        assert await provider.load_access_token(token) is None

    asyncio.run(run())


def test_full_oauth_flow_via_http(oauth_config):
    app = _build_mcp_app()
    server, thread, base = _start_server(app)
    try:
        # 1. Dynamic client registration (RFC 7591)
        r = httpx.post(base + "/register", json={
            "redirect_uris": ["http://localhost:9999/callback"],
            "token_endpoint_auth_method": "client_secret_post",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": " ".join(SCOPES),
        })
        assert r.status_code == 201
        client = r.json()
        client_id = client["client_id"]
        client_secret = client["client_secret"]

        # 2. /authorize with PKCE S256
        verifier = "test-verifier-0123456789abcdef0123456789abcdef"
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        r = httpx.get(base + "/authorize", params={
            "client_id": client_id,
            "redirect_uri": "http://localhost:9999/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": " ".join(SCOPES),
        })
        assert r.status_code == 302
        location = r.headers["location"]
        query = parse_qs(urlparse(location).query)
        code = query["code"][0]
        assert query["state"] == ["xyz"]

        # 3. /token exchange
        r = httpx.post(base + "/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9999/callback",
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        })
        assert r.status_code == 200
        tokens = r.json()
        access_token = tokens["access_token"]
        assert tokens["token_type"] == "Bearer"
        assert tokens["refresh_token"]

        # 4. Access token works on /mcp
        r = httpx.post(base + "/mcp", json={}, headers={"Authorization": f"Bearer {access_token}"})
        assert r.status_code != 401

        # 5. One-time code: reusing it fails
        r = httpx.post(base + "/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9999/callback",
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

        # 6. PKCE: wrong verifier rejected (fresh code)
        r = httpx.get(base + "/authorize", params={
            "client_id": client_id,
            "redirect_uri": "http://localhost:9999/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": " ".join(SCOPES),
        })
        code2 = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
        r = httpx.post(base + "/token", data={
            "grant_type": "authorization_code",
            "code": code2,
            "redirect_uri": "http://localhost:9999/callback",
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": "wrong-verifier",
        })
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

        # 7. Unsupported grant type rejected
        r = httpx.post(base + "/token", data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
        })
        assert r.status_code == 400
    finally:
        _stop_server(server, thread)


# ── OAuth state persistence (server restart survival) ────────────────────────

def test_oauth_state_persists_across_restart(tmp_path):
    """Registered clients + refresh/access tokens survive a provider restart."""
    state_file = str(tmp_path / "oauth_state.json")
    p1 = oauth.InMemoryAuthProvider(SCOPES, state_file=state_file)

    async def setup():
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        client = OAuthClientInformationFull(
            client_id="persist-client",
            client_secret="persist-secret",
            redirect_uris=[AnyHttpUrl("http://localhost:9999/cb")],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(SCOPES),
        )
        await p1.register_client(client)
        redirect = await p1.authorize(
            client,
            AuthorizationParams(
                state="s", scopes=SCOPES, code_challenge="ch",
                redirect_uri=AnyHttpUrl("http://localhost:9999/cb"),
                redirect_uri_provided_explicitly=True,
            ),
        )
        code = parse_qs(urlparse(redirect).query)["code"][0]
        auth_code = await p1.load_authorization_code(client, code)
        tokens = await p1.exchange_authorization_code(client, auth_code)
        return tokens

    tokens = asyncio.run(setup())

    # Simulate a server restart: a brand-new provider loads from disk.
    p2 = oauth.InMemoryAuthProvider(SCOPES, state_file=state_file)
    assert p2._clients["persist-client"].client_id == "persist-client"
    assert p2._clients["persist-client"].client_secret == "persist-secret"
    assert tokens.refresh_token in p2._refresh_tokens
    assert tokens.access_token in p2._access_tokens

    # The restored refresh token can be exchanged (rotation works).
    async def refresh():
        rt = await p2.load_refresh_token(
            p2._clients["persist-client"], tokens.refresh_token
        )
        assert rt is not None
        new_tokens = await p2.exchange_refresh_token(
            p2._clients["persist-client"], rt, SCOPES
        )
        assert new_tokens.refresh_token != tokens.refresh_token

    asyncio.run(refresh())


def test_oauth_state_never_persists_authorization_codes(tmp_path):
    """Authorization codes are short-lived and must never hit the state file."""
    state_file = str(tmp_path / "oauth_state.json")
    p = oauth.InMemoryAuthProvider(SCOPES, state_file=state_file)

    async def run():
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        client = OAuthClientInformationFull(
            client_id="code-client",
            redirect_uris=[AnyHttpUrl("http://localhost:9999/cb")],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(SCOPES),
        )
        await p.register_client(client)
        redirect = await p.authorize(
            client,
            AuthorizationParams(
                state="s", scopes=SCOPES, code_challenge="ch",
                redirect_uri=AnyHttpUrl("http://localhost:9999/cb"),
                redirect_uri_provided_explicitly=True,
            ),
        )
        return parse_qs(urlparse(redirect).query)["code"][0]

    code = asyncio.run(run())
    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "codes" not in data
    assert code not in json.dumps(data)


def test_oauth_state_file_permissions(tmp_path):
    """The persisted OAuth state file must be chmod 0600 (POSIX)."""
    state_file = str(tmp_path / "oauth_state.json")
    p = oauth.InMemoryAuthProvider(SCOPES, state_file=state_file)

    async def run():
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        client = OAuthClientInformationFull(
            client_id="perm-client",
            redirect_uris=[AnyHttpUrl("http://localhost:9999/cb")],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(SCOPES),
        )
        await p.register_client(client)

    asyncio.run(run())
    assert os.path.exists(state_file)
    if os.name != "nt":
        import stat
        mode = stat.S_IMODE(os.stat(state_file).st_mode)
        assert mode == 0o600


def test_oauth_survives_server_restart(oauth_config):
    """A full HTTP OAuth session survives a simulated server restart."""
    state_file = os.path.join(config.CONFIG_DIR, "oauth_state.json")
    if os.path.exists(state_file):
        os.remove(state_file)
    try:
        # 1. First server: register client + get tokens.
        app = _build_mcp_app()
        server, thread, base = _start_server(app)
        try:
            r = httpx.post(base + "/register", json={
                "redirect_uris": ["http://localhost:9999/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": " ".join(SCOPES),
            })
            assert r.status_code == 201
            client = r.json()
            client_id = client["client_id"]
            client_secret = client["client_secret"]

            verifier = "test-verifier-0123456789abcdef0123456789abcdef"
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            ).decode().rstrip("=")
            r = httpx.get(base + "/authorize", params={
                "client_id": client_id,
                "redirect_uri": "http://localhost:9999/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                "scope": " ".join(SCOPES),
            })
            code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
            r = httpx.post(base + "/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:9999/callback",
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": verifier,
            })
            assert r.status_code == 200
            tokens = r.json()
            access_token = tokens["access_token"]
            refresh_token = tokens["refresh_token"]
        finally:
            _stop_server(server, thread)

        # 2. Simulate a server restart: fresh AS provider + fresh app.
        oauth.reset_auth_server_provider()
        reset_auth_provider()
        app2 = _build_mcp_app()
        server2, thread2, base2 = _start_server(app2)
        try:
            # The old access token still works (no re-authorization needed).
            r = httpx.post(
                base2 + "/mcp", json={},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert r.status_code != 401
            # The old refresh token still works (rotation issues a new pair).
            r = httpx.post(base2 + "/token", data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            })
            assert r.status_code == 200
            assert r.json()["access_token"]
            assert r.json()["refresh_token"] != refresh_token
        finally:
            _stop_server(server2, thread2)
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)