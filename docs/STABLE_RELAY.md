# Stable Relay (domain-free clients)

The stable relay gives users a permanent MCP URL without asking them to buy a domain or create a Cloudflare Tunnel.

```
ChatGPT -> https://relay.walnutnest.buzz/d/<device-id>/mcp
        -> Cloudflare Worker / Durable Object
        -> outbound WebSocket already opened by Termux
        -> http://127.0.0.1:8765/mcp
```

## Identity and security

On first relay start the client creates two random values in `~/.config/termux-mcp/config.env` (mode 0600): a public device id used in the URL and a 256-bit device secret used only to claim the relay WebSocket. The Durable Object stores only SHA-256 of the device secret. A newer authenticated device connection replaces the older one.

The device id is routing information, not authorization. The public request's `Authorization` header is forwarded to the local MCP server and is still validated there. The relay does not log request bodies or authorization headers. As with any TLS reverse proxy, the relay runtime can technically observe plaintext HTTP after TLS termination; users who require infrastructure-level secrecy should use the existing self-hosted named-tunnel/custom-domain mode.

## Deployment

The Worker source is in `relay-worker/`. Deploy from a desktop/CI environment with Wrangler (Wrangler's local `workerd` binary does not support Android/Termux arm64):

```
cd relay-worker
npm install
npx wrangler deploy
```

Then bind `relay.walnutnest.buzz/*` to the Worker in Cloudflare (or change `TERMUX_MCP_RELAY_BASE`). After the public relay is deployed and `/health` answers, `relay` can become the default first-run provider.

## Client

```
termux-mcp start --tunnel relay
```

The generated URL survives MCP restarts, Termux restarts, and phone reboots as long as the config directory is preserved. Reinstall/migration recovery should restore the relay device id + secret together; a later release will expose a user-friendly recovery code rather than asking users to copy secrets.
