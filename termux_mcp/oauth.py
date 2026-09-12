"""OAuth 2.0 authorization-server + protected-resource support.

Architecture (clean separation):
  A. MCP Resource Server — validates Bearer tokens on /mcp (the static
     token and/or OAuth access tokens) and serves RFC 9728 protected
     resource metadata.
  B. Authorization Server — self-hosted, standards-compliant
     authorization-code + PKCE (RFC 6749 + RFC 7636) flow built on the
     official `mcp` SDK abstractions (OAuthAuthorizationServerProvider,
     AuthorizationHandler, TokenHandler, RegistrationHandler). PKCE S256
     verification, one-time authorization codes, exact redirect_uri
     matching, and refresh-token rotation are all handled by the SDK.

OAuth mode is enabled by setting TERMUX_MCP_OAUTH_ISSUER. The issuer may
be a concrete URL or the special value "auto", which resolves to the
current public URL (runtime tunnel URL > TERMUX_MCP_PUBLIC_URL) so the
metadata stays correct even though tunnel URLs change on restart.

All metadata handlers resolve the public URL / issuer at request time and
never trust Host / X-Forwarded-* headers. No tokens or client secrets are
ever logged. Registered clients and refresh/access tokens are persisted to
~/.config/termux-mcp/oauth_state.json (chmod 0600) so a server restart does
not invalidate an established OAuth session; authorization codes are never
persisted.
"""

import json
import os
import secrets
import threading
import time
from typing import List, Optional
from urllib.parse import urlparse

from . import config

# OAuth discovery / authorization-server endpoints that must be reachable
# without a Bearer token so MCP clients can complete the OAuth flow.
_PUBLIC_PATHS = {"/authorize", "/token", "/register", "/revoke"}

# Persistent OAuth state (registered clients + refresh/access tokens) so a
# server restart does not force clients to re-authorize. Authorization codes
# are NEVER persisted. The file is chmod 0600 and written atomically.
_OAUTH_STATE_FILE: str = os.path.join(config.CONFIG_DIR, "oauth_state.json")


def oauth_enabled() -> bool:
    """True when OAuth mode is configured (TERMUX_MCP_OAUTH_ISSUER set)."""
    issuer = config.OAUTH_ISSUER.strip()
    if not issuer:
        return False
    if issuer == "auto":
        return True
    return _valid_http_url(issuer)


def get_scopes() -> List[str]:
    """Configured OAuth scopes (space-separated TERMUX_MCP_OAUTH_SCOPES)."""
    return [s for s in config.OAUTH_SCOPES.split() if s]


def get_public_url() -> Optional[str]:
    """Externally reachable MCP base URL (runtime > config), or None."""
    url = config.get_public_url().strip().rstrip("/")
    return url or None


def get_issuer() -> Optional[str]:
    """Resolved OAuth authorization-server issuer, or None.

    A concrete TERMUX_MCP_OAUTH_ISSUER is used as-is; "auto" resolves to
    the current public URL. None means the issuer cannot be determined yet
    (e.g. "auto" with no public URL known).
    """
    if not oauth_enabled():
        return None
    issuer = config.OAUTH_ISSUER.strip()
    if issuer and issuer != "auto":
        return issuer.rstrip("/")
    pub = get_public_url()
    return pub.rstrip("/") if pub else None


def get_resource_url() -> Optional[str]:
    """Externally visible MCP resource URL (https://host/mcp), or None."""
    pub = get_public_url()
    if pub:
        return pub + "/mcp"
    issuer = get_issuer()
    if issuer:
        return issuer + "/mcp"
    return None


def get_metadata_url() -> Optional[str]:
    """RFC 9728 protected-resource metadata URL for this MCP resource."""
    resource = get_resource_url()
    if not resource:
        return None
    parsed = urlparse(resource)
    return (
        f"{parsed.scheme}://{parsed.netloc}"
        f"/.well-known/oauth-protected-resource{parsed.path}"
    )


def is_public_path(path: str) -> bool:
    """True for OAuth discovery / AS endpoints that must not require a token.

    Only meaningful when OAuth is enabled — when it is disabled there are
    no discovery routes, so every path stays protected by the middleware.
    """
    if not oauth_enabled():
        return False
    return path in _PUBLIC_PATHS or path.startswith("/.well-known/")


def _valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ── Authorization Server provider ────────────────────────────────────────────

class InMemoryAuthProvider:
    """OAuth Authorization Server (RFC 6749 + RFC 7636) with disk persistence.

    Implements the `mcp` SDK's OAuthAuthorizationServerProvider protocol.
    Registered clients and refresh/access tokens are persisted to a chmod-0600
    JSON file so a server restart does not invalidate an established OAuth
    session (the client can keep refreshing without re-authorizing).
    Authorization codes are short-lived, one-time, and NEVER persisted.
    """

    def __init__(
        self,
        scopes: List[str],
        code_ttl: float = 60.0,
        access_ttl: int = 3600,
        refresh_ttl: int = 7 * 24 * 3600,
        state_file: Optional[str] = None,
    ):
        self._scopes = scopes
        self._code_ttl = code_ttl
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._clients = {}
        self._codes = {}
        self._refresh_tokens = {}
        self._access_tokens = {}
        self._state_file = state_file or _OAUTH_STATE_FILE
        self._lock = threading.Lock()
        self._load_state()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """Restore clients + refresh/access tokens from disk (expired dropped).

        Authorization codes are never stored, so an in-flight flow is not
        resumable across a restart — only established sessions survive.
        """
        if not self._state_file:
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        from mcp.server.auth.provider import AccessToken, RefreshToken
        from mcp.shared.auth import OAuthClientInformationFull

        now = time.time()
        for cid, raw in (data.get("clients") or {}).items():
            try:
                self._clients[cid] = OAuthClientInformationFull.model_validate(raw)
            except Exception:
                continue
        for tok, raw in (data.get("refresh_tokens") or {}).items():
            try:
                rt = RefreshToken.model_validate(raw)
            except Exception:
                continue
            if rt.expires_at and rt.expires_at < now:
                continue
            self._refresh_tokens[tok] = rt
        for tok, raw in (data.get("access_tokens") or {}).items():
            try:
                at = AccessToken.model_validate(raw)
            except Exception:
                continue
            if at.expires_at and at.expires_at < now:
                continue
            self._access_tokens[tok] = at

    def _save_state(self) -> None:
        """Persist clients + refresh/access tokens (never authorization codes)."""
        if not self._state_file:
            return
        data = {
            "clients": {
                cid: c.model_dump(mode="json") for cid, c in self._clients.items()
            },
            "refresh_tokens": {
                t: rt.model_dump(mode="json") for t, rt in self._refresh_tokens.items()
            },
            "access_tokens": {
                t: at.model_dump(mode="json") for t, at in self._access_tokens.items()
            },
        }
        os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
        tmp = self._state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._state_file)

    # ── SDK provider protocol ────────────────────────────────────────────────

    async def get_client(self, client_id: str):
        return self._clients.get(client_id)

    async def register_client(self, client_info) -> None:
        with self._lock:
            self._clients[client_info.client_id] = client_info
            self._save_state()

    async def authorize(self, client, params) -> str:
        """Generate a short-lived, one-time authorization code and redirect."""
        from mcp.server.auth.provider import AuthorizationCode, construct_redirect_uri

        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or self._scopes,
            expires_at=time.time() + self._code_ttl,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=None,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client, authorization_code: str):
        code = self._codes.get(authorization_code)
        if code is None:
            return None
        if code.expires_at < time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(self, client, authorization_code):
        # One-time use: the code is consumed by this exchange.
        with self._lock:
            self._codes.pop(authorization_code.code, None)
            token = self._issue_tokens(
                client, authorization_code.scopes, subject=authorization_code.subject
            )
            self._save_state()
            return token

    async def load_refresh_token(self, client, refresh_token: str):
        with self._lock:
            token = self._refresh_tokens.get(refresh_token)
            if token is None:
                return None
            if token.expires_at and token.expires_at < time.time():
                self._refresh_tokens.pop(refresh_token, None)
                self._save_state()
                return None
            return token

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        # Rotation: the presented refresh token is revoked and replaced.
        with self._lock:
            self._refresh_tokens.pop(refresh_token.token, None)
            token = self._issue_tokens(client, scopes, subject=refresh_token.subject)
            self._save_state()
            return token

    async def load_access_token(self, token: str):
        with self._lock:
            access = self._access_tokens.get(token)
            if access is None:
                return None
            if access.expires_at and access.expires_at < time.time():
                self._access_tokens.pop(token, None)
                self._save_state()
                return None
            return access

    async def revoke_token(self, token) -> None:
        from mcp.server.auth.provider import AccessToken, RefreshToken

        with self._lock:
            if isinstance(token, AccessToken):
                self._access_tokens.pop(token.token, None)
            elif isinstance(token, RefreshToken):
                self._refresh_tokens.pop(token.token, None)
            self._save_state()

    def _issue_tokens(self, client, scopes, subject=None):
        from mcp.server.auth.provider import AccessToken, RefreshToken
        from mcp.shared.auth import OAuthToken

        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = int(time.time())
        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=now + self._access_ttl,
            subject=subject,
        )
        self._refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=now + self._refresh_ttl,
            subject=subject,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._access_ttl,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )


_auth_server_provider: Optional[InMemoryAuthProvider] = None


def get_auth_server_provider() -> InMemoryAuthProvider:
    """Process-wide Authorization Server provider (lazily created)."""
    global _auth_server_provider
    if _auth_server_provider is None:
        _auth_server_provider = InMemoryAuthProvider(get_scopes())
    return _auth_server_provider


def reset_auth_server_provider() -> None:
    """Drop the cached AS provider (used by tests)."""
    global _auth_server_provider
    _auth_server_provider = None


def get_token_verifier():
    """SDK TokenVerifier that validates access tokens issued by our AS."""
    from mcp.server.auth.provider import ProviderTokenVerifier

    return ProviderTokenVerifier(get_auth_server_provider())


# ── Dynamic metadata handlers ────────────────────────────────────────────────

class _DynamicAuthServerMetadataHandler:
    """Serves RFC 8414 AS metadata resolved from the current public URL."""

    async def handle(self, request):
        from pydantic import AnyHttpUrl
        from starlette.responses import JSONResponse

        from mcp.server.auth.json_response import PydanticJSONResponse
        from mcp.shared.auth import OAuthMetadata

        issuer = get_issuer()
        if not issuer:
            return JSONResponse({"error": "not_found"}, status_code=404)
        metadata = OAuthMetadata(
            issuer=AnyHttpUrl(issuer),
            authorization_endpoint=AnyHttpUrl(issuer + "/authorize"),
            token_endpoint=AnyHttpUrl(issuer + "/token"),
            registration_endpoint=AnyHttpUrl(issuer + "/register"),
            revocation_endpoint=AnyHttpUrl(issuer + "/revoke"),
            scopes_supported=get_scopes(),
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"],
            code_challenge_methods_supported=["S256"],
        )
        return PydanticJSONResponse(
            content=metadata,
            headers={"Cache-Control": "public, max-age=3600"},
        )


class _DynamicProtectedResourceHandler:
    """Serves RFC 9728 protected-resource metadata (dynamic resource URL)."""

    async def handle(self, request):
        from pydantic import AnyHttpUrl
        from starlette.responses import JSONResponse

        from mcp.server.auth.json_response import PydanticJSONResponse
        from mcp.shared.auth import ProtectedResourceMetadata

        resource = get_resource_url()
        issuer = get_issuer()
        if not resource or not issuer:
            return JSONResponse({"error": "not_found"}, status_code=404)
        metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl(resource),
            authorization_servers=[AnyHttpUrl(issuer)],
            scopes_supported=get_scopes(),
            bearer_methods_supported=["header"],
        )
        return PydanticJSONResponse(
            content=metadata,
            headers={"Cache-Control": "public, max-age=3600"},
        )


# ── Route builders ───────────────────────────────────────────────────────────

def build_auth_routes() -> list:
    """Authorization Server routes (RFC 8414 metadata + RFC 6749 endpoints).

    Built on the official SDK handlers so PKCE S256 verification, one-time
    authorization codes, exact redirect_uri matching, and refresh-token
    rotation are handled by the SDK's TokenHandler.
    """
    from mcp.server.auth.handlers.authorize import AuthorizationHandler
    from mcp.server.auth.handlers.register import RegistrationHandler
    from mcp.server.auth.handlers.revoke import RevocationHandler
    from mcp.server.auth.handlers.token import TokenHandler
    from mcp.server.auth.middleware.client_auth import ClientAuthenticator
    from mcp.server.auth.routes import cors_middleware
    from mcp.server.auth.settings import ClientRegistrationOptions
    from starlette.routing import Route

    provider = get_auth_server_provider()
    client_authenticator = ClientAuthenticator(provider)
    registration_options = ClientRegistrationOptions(
        enabled=True,
        valid_scopes=get_scopes(),
        default_scopes=get_scopes(),
    )
    return [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(
                _DynamicAuthServerMetadataHandler().handle, ["GET", "OPTIONS"]
            ),
            methods=["GET", "OPTIONS"],
        ),
        Route(
            "/authorize",
            endpoint=AuthorizationHandler(provider).handle,
            methods=["GET", "POST"],
        ),
        Route(
            "/token",
            endpoint=cors_middleware(
                TokenHandler(provider, client_authenticator).handle, ["POST", "OPTIONS"]
            ),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/register",
            endpoint=cors_middleware(
                RegistrationHandler(provider, registration_options).handle,
                ["POST", "OPTIONS"],
            ),
            methods=["POST", "OPTIONS"],
        ),
        Route(
            "/revoke",
            endpoint=cors_middleware(
                RevocationHandler(provider, client_authenticator).handle,
                ["POST", "OPTIONS"],
            ),
            methods=["POST", "OPTIONS"],
        ),
    ]


def build_protected_resource_routes() -> list:
    """RFC 9728 protected-resource metadata routes (host-form + path-form)."""
    from mcp.server.auth.routes import cors_middleware
    from starlette.routing import Route

    handler = _DynamicProtectedResourceHandler()
    return [
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/mcp",
            endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
            methods=["GET", "OPTIONS"],
        ),
    ]