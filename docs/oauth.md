# MCP OAuth & Auth Discovery

termux-mcp supports two authentication modes for the MCP Streamable HTTP
endpoint (`/mcp`):

1. **Static Bearer token** (default) — `Authorization: Bearer <token>`
   header only. Tokens in URL query parameters are never accepted.
2. **OAuth 2.0 (authorization-code + PKCE)** — a self-hosted, standards
   compliant authorization server built on the official `mcp` Python SDK
   abstractions, plus RFC 9728 protected-resource metadata for discovery.

Both modes can be active at once: the static Bearer token always remains
valid, and OAuth access tokens are accepted in addition when OAuth mode is
configured.

## Architecture

The implementation cleanly separates the two OAuth roles:

- **A. MCP Resource Server** — validates Bearer tokens on `/mcp` (static
  token and/or OAuth access tokens) and serves RFC 9728 protected-resource
  metadata.
- **B. Authorization Server** — self-hosted on the same process, issuing
  access/refresh tokens via the authorization-code + PKCE flow (RFC 6749 +
  RFC 7636). Dynamic client registration (RFC 7591) and token revocation
  (RFC 7009) are supported.

No external Authorization Server is required. The SDK's
`OAuthAuthorizationServerProvider` protocol, `AuthorizationHandler`,
`TokenHandler`, `RegistrationHandler`, and `RevocationHandler` are used
directly, so PKCE S256 verification, one-time authorization codes, exact
`redirect_uri` matching, and refresh-token rotation are handled by the
official SDK.

## Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `TERMUX_MCP_OAUTH_ISSUER` | Enables OAuth mode. A concrete URL (e.g. `https://mcp.example.com`) or the special value `auto`, which resolves the issuer to the current public URL. | unset (OAuth disabled) |
| `TERMUX_MCP_PUBLIC_URL` | Externally visible MCP base URL (e.g. `https://mcp.example.com`). Used for the protected-resource `resource` field and the `WWW-Authenticate` challenge. | unset |
| `TERMUX_MCP_OAUTH_SCOPES` | Space-separated scopes advertised and required. | `mcp:read mcp:write` |

The public URL is resolved in this order:

1. **Runtime** — written by `termux-mcp start` after a tunnel starts
   (`~/.local/state/termux-mcp/public_url`). This is how the dynamic
   Pinggy/Cloudflare URL is propagated to the server process.
2. **Configured** — `TERMUX_MCP_PUBLIC_URL`.
3. **Issuer** — a concrete `TERMUX_MCP_OAUTH_ISSUER` (used as the resource
   base when no public URL is known).

Metadata is always resolved at request time and **never trusts
`Host` / `X-Forwarded-*` headers**.

### Example: OAuth with a dynamic tunnel

```bash
export TERMUX_MCP_OAUTH_ISSUER=auto
termux-mcp start --tunnel auto
```

After the tunnel starts, the runtime public URL is recorded and the
metadata/challenge advertise the real tunnel URL.

### Example: OAuth with a stable custom domain

```bash
export TERMUX_MCP_OAUTH_ISSUER=https://mcp.example.com
export TERMUX_MCP_PUBLIC_URL=https://mcp.example.com
termux-mcp start --no-tunnel
```

## Discovery endpoints

When OAuth is enabled, the MCP server exposes:

| Endpoint | Spec | Purpose |
| --- | --- | --- |
| `/.well-known/oauth-authorization-server` | RFC 8414 | AS metadata: issuer, `/authorize`, `/token`, `/register`, `/revoke`, scopes, PKCE S256 |
| `/.well-known/oauth-protected-resource` | RFC 9728 | Protected-resource metadata (host form) |
| `/.well-known/oauth-protected-resource/mcp` | RFC 9728 | Protected-resource metadata (path form) |
| `/authorize` | RFC 6749 | Authorization endpoint (code + PKCE) |
| `/token` | RFC 6749 | Token endpoint (authorization_code / refresh_token grants) |
| `/register` | RFC 7591 | Dynamic client registration |
| `/revoke` | RFC 7009 | Token revocation |

The protected-resource metadata contains `resource` (the externally
visible `/mcp` URL), `authorization_servers`, `scopes_supported`, and
`bearer_methods_supported: ["header"]`.

Unauthenticated requests to `/mcp` return `401` with a JSON body
`{"error": "Unauthorized"}` and a standards-compliant challenge:

```
WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource/mcp", scope="mcp:read mcp:write"
```

When OAuth is disabled, the challenge is simply `WWW-Authenticate: Bearer`
and no discovery endpoints are advertised.

## Security model

- Authorization-code flow with **PKCE S256 required** (the SDK rejects
  requests without a valid `code_verifier`).
- **Exact `redirect_uri` validation** against the registered client.
- **Short-lived, one-time authorization codes** (60 s, consumed on
  exchange).
- **Access-token expiry** (1 h) and **refresh-token rotation** (7 d,
  old token revoked on refresh).
- **Dynamic client registration** issues a random `client_secret`
  (`secrets.token_hex(32)`).
- Unsupported grant types are rejected.
- No tokens in URL query parameters; no plaintext secrets logged.
- Constant-time comparison (`hmac.compare_digest`) for the static token.
- **Persistent AS state**: registered clients and refresh/access tokens are
  persisted to `~/.config/termux-mcp/oauth_state.json` (chmod 0600, atomic
  write via temp file + `os.replace`, guarded by a lock). A server-only
  `termux-mcp restart` therefore does **not** invalidate an established
  OAuth session — the client can keep refreshing without re-authorizing.
- **Authorization codes are never persisted**: they are short-lived (60 s),
  one-time, and kept in memory only, so an in-flight flow is not resumable
  across a restart — only established sessions survive.
- Expired refresh/access tokens are dropped on load and on use.
- OAuth mode never silently disables authentication: when enabled, `/mcp`
  requires a valid static token or OAuth access token.

## Local test procedure

```bash
# 1. Enable OAuth with a local issuer (http://127.0.0.1 is allowed for testing)
export TERMUX_MCP_OAUTH_ISSUER=http://127.0.0.1:8765
export TERMUX_MCP_PUBLIC_URL=http://127.0.0.1:8765
termux-mcp start --no-tunnel

# 2. Discovery
curl -i http://127.0.0.1:8765/.well-known/oauth-protected-resource/mcp
curl -i http://127.0.0.1:8765/.well-known/oauth-authorization-server

# 3. Unauthenticated /mcp shows the challenge
curl -i http://127.0.0.1:8765/mcp
```

## Public tunnel test procedure

```bash
export TERMUX_MCP_OAUTH_ISSUER=auto
termux-mcp start --tunnel auto
# note the printed public URL, e.g. https://xxxxx.free.pinggy.net/mcp

curl -i https://xxxxx.free.pinggy.net/.well-known/oauth-protected-resource/mcp
curl -i https://xxxxx.free.pinggy.net/mcp   # expect 401 + WWW-Authenticate
```

## ChatGPT / custom MCP clients

The server implements the OAuth discovery + authorization-code + PKCE flow
that MCP clients are expected to use. The full chain
**ChatGPT → OAuth → Pinggy tunnel → Termux-MCP → Android** has been
verified end-to-end on a real device. The static Bearer token remains the
verified path for clients that support custom headers.

## Restart survival

Anonymous tunnel hostnames change whenever the tunnel is rebuilt, but a
plain `termux-mcp restart` is **server-only**: the running tunnel, its PID
and the verified public URL are preserved, so ChatGPT's saved MCP URL stays
valid. On startup the server re-reads the persisted public URL
(`~/.local/state/termux-mcp/public_url`) and restores:

- the FastMCP DNS-rebinding `allowed_hosts` entry for the tunnel host
  (seeded at app build and kept in sync by the watcher thread), and
- the OAuth issuer / protected-resource metadata when
  `TERMUX_MCP_OAUTH_ISSUER=auto` (resolved from the same runtime URL).

Registered clients and refresh/access tokens are restored from
`~/.config/termux-mcp/oauth_state.json`, so the client does not need to
re-authorize. Only `termux-mcp restart --tunnel <mode>` (rebuild) or
`--no-tunnel` (stop) changes the public URL.

## SDK / spec assumptions

- Requires `mcp>=1.28,<2` (the `mcp.server.auth` module).
- The SDK's `RequireAuthMiddleware` is intentionally **not** used: it
  changes the 401 body to `{"error": "invalid_token"}`, which would break
  the tunnel health check that expects `{"error": "Unauthorized"}`. The
  custom middleware preserves the existing 401 shape while adding the
  `WWW-Authenticate` challenge.
- The AS metadata is served by a dynamic handler because the tunnel URL
  changes on restart; the SDK's static `create_auth_routes()` metadata is
  not suitable for that case.