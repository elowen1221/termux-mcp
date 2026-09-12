"""Authentication abstraction for termux-mcp.

Two authentication sources can be active at once:

  * Static Bearer token — `Authorization: Bearer <token>` header only;
    tokens in URL query parameters are never accepted. This is the
    default and always remains valid.
  * OAuth 2.0 access tokens issued by the self-hosted authorization
    server (see termux_mcp/oauth.py and docs/oauth.md). OAuth mode is
    enabled by setting TERMUX_MCP_OAUTH_ISSUER.

The REST/WebSocket handlers use the synchronous `authenticate()` path
(static Bearer only, unchanged). The MCP Streamable HTTP middleware uses
the asynchronous `authenticate_async()` path, which accepts either the
static Bearer token or a valid OAuth access token.
"""

import hmac
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import AUTH_TOKEN, REQUIRE_AUTH


@dataclass
class AuthResult:
    """Structured outcome of an authentication attempt."""

    authorized: bool
    scopes: Optional[List[str]] = None
    client_id: Optional[str] = None
    subject: Optional[str] = None
    error: Optional[str] = None  # "invalid_token" | "insufficient_scope" | ...


def _extract_bearer_token(headers: Dict[str, str]) -> str:
    """Return the Bearer token from the Authorization header (or "")."""
    for key, value in headers.items():
        if key.lower() == "authorization" and value.startswith("Bearer "):
            return value[7:]
    return ""


class AuthProvider(ABC):
    """Interface for authenticating incoming requests."""

    @abstractmethod
    def authenticate(self, headers: Dict[str, str]) -> bool:
        """Return True when the request is authorized (sync path)."""

    async def authenticate_async(self, headers: Dict[str, str]) -> AuthResult:
        """Structured authentication for the async MCP middleware path."""
        return AuthResult(authorized=self.authenticate(headers))

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """True when this provider enforces authentication."""

    def challenge_headers(self) -> Dict[str, str]:
        """WWW-Authenticate headers to send on 401."""
        return {"WWW-Authenticate": "Bearer"}


class BearerAuthProvider(AuthProvider):
    """Static Bearer token authentication (Authorization header only)."""

    def __init__(self, token: str = "", required: Optional[bool] = None):
        self._token = token
        self._required = REQUIRE_AUTH if required is None else required

    @property
    def enabled(self) -> bool:
        return self._required

    def authenticate(self, headers: Dict[str, str]) -> bool:
        if not self._required:
            return True
        token = _extract_bearer_token(headers)
        if token:
            return hmac.compare_digest(token, self._token)
        return False


class OAuthAuthProvider(AuthProvider):
    """Validates OAuth access tokens issued by the self-hosted AS.

    Token verification is asynchronous (the SDK TokenVerifier protocol is
    async), so this provider only participates in the async MCP path. The
    sync REST/WebSocket path continues to use the static Bearer token.
    """

    def __init__(self, token_verifier, scopes: List[str]):
        self._verifier = token_verifier
        self._scopes = scopes

    @property
    def enabled(self) -> bool:
        return True

    def authenticate(self, headers: Dict[str, str]) -> bool:
        return False  # async verification only

    async def authenticate_async(self, headers: Dict[str, str]) -> AuthResult:
        token = _extract_bearer_token(headers)
        if not token:
            return AuthResult(authorized=False)
        access = await self._verifier.verify_token(token)
        if access is None:
            return AuthResult(authorized=False, error="invalid_token")
        if access.expires_at and access.expires_at < int(time.time()):
            return AuthResult(authorized=False, error="invalid_token")
        missing = [s for s in self._scopes if s not in (access.scopes or [])]
        if missing:
            return AuthResult(
                authorized=False, error="insufficient_scope", scopes=access.scopes
            )
        return AuthResult(
            authorized=True,
            scopes=access.scopes,
            client_id=access.client_id,
            subject=access.subject,
        )


class CompositeAuthProvider(AuthProvider):
    """Tries multiple providers; the first success authorizes the request."""

    def __init__(self, providers: List[AuthProvider]):
        self._providers = providers

    @property
    def enabled(self) -> bool:
        return any(p.enabled for p in self._providers)

    def authenticate(self, headers: Dict[str, str]) -> bool:
        """Sync path (REST/WebSocket): static Bearer only, unchanged."""
        if not self.enabled:
            return True
        for p in self._providers:
            if p.authenticate(headers):
                return True
        return False

    async def authenticate_async(self, headers: Dict[str, str]) -> AuthResult:
        for p in self._providers:
            if not p.enabled:
                continue
            result = await p.authenticate_async(headers)
            if result.authorized:
                return result
        return AuthResult(authorized=False)

    def challenge_headers(self) -> Dict[str, str]:
        from . import oauth

        challenge = "Bearer"
        if oauth.oauth_enabled():
            parts = []
            meta = oauth.get_metadata_url()
            if meta:
                parts.append(f'resource_metadata="{meta}"')
            scopes = oauth.get_scopes()
            if scopes:
                parts.append(f'scope="{" ".join(scopes)}"')
            if parts:
                challenge += " " + ", ".join(parts)
        return {"WWW-Authenticate": challenge}


_provider: Optional[AuthProvider] = None


def _build_oauth_auth_provider() -> Optional[OAuthAuthProvider]:
    from . import oauth

    if not oauth.oauth_enabled():
        return None
    return OAuthAuthProvider(oauth.get_token_verifier(), oauth.get_scopes())


def get_auth_provider() -> AuthProvider:
    """Return the process-wide auth provider (lazily created)."""
    global _provider
    if _provider is None:
        providers: List[AuthProvider] = [BearerAuthProvider(AUTH_TOKEN)]
        oauth_provider = _build_oauth_auth_provider()
        if oauth_provider is not None:
            providers.append(oauth_provider)
        _provider = (
            CompositeAuthProvider(providers) if len(providers) > 1 else providers[0]
        )
    return _provider


def reset_auth_provider() -> None:
    """Drop the cached provider (used by tests)."""
    global _provider
    _provider = None