"""Zero-config stable relay client for Termux-MCP.

A device keeps one outbound WebSocket to the project relay. Incoming HTTP MCP
requests are delivered as small JSON envelopes and proxied to the local MCP
endpoint. The public URL is stable because it is derived from a persistent,
random device id rather than an anonymous tunnel hostname.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import config

DEFAULT_RELAY_BASE = "https://relay.walnutnest.buzz"
RELAY_BASE = os.environ.get("TERMUX_MCP_RELAY_BASE", DEFAULT_RELAY_BASE).rstrip("/")


def _new_device_id() -> str:
    return secrets.token_urlsafe(12).lower().replace("_", "-")


def _new_device_secret() -> str:
    return secrets.token_urlsafe(32)


def ensure_identity() -> tuple[str, str]:
    """Return the persistent relay identity, creating it on first use."""
    device_id = config._FILE_VALUES.get("TERMUX_MCP_RELAY_DEVICE_ID", "").strip()
    secret = config._FILE_VALUES.get("TERMUX_MCP_RELAY_SECRET", "").strip()
    if not device_id or not secret:
        device_id = device_id or _new_device_id()
        secret = secret or _new_device_secret()
        config._write_config({
            "TERMUX_MCP_RELAY_DEVICE_ID": device_id,
            "TERMUX_MCP_RELAY_SECRET": secret,
        })
    return device_id, secret


def public_url(device_id: str | None = None) -> str:
    device_id = device_id or ensure_identity()[0]
    return f"{RELAY_BASE}/d/{device_id}"


def websocket_url(device_id: str, secret: str) -> str:
    scheme = "wss" if RELAY_BASE.startswith("https://") else "ws"
    host = RELAY_BASE.split("://", 1)[-1]
    return f"{scheme}://{host}/connect/{device_id}"


@dataclass
class RelayResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _local_request(message: dict[str, Any]) -> RelayResponse:
    """Proxy one relay request to the loopback MCP endpoint."""
    method = str(message.get("method", "POST")).upper()
    path = str(message.get("path", "/mcp"))
    if not path.startswith("/mcp"):
        return RelayResponse(404, {"content-type": "text/plain"}, b"not found")
    raw = base64.b64decode(message.get("body", "") or "")
    incoming = message.get("headers") or {}
    headers = {
        k: v for k, v in incoming.items()
        if k.lower() in {"content-type", "accept", "authorization", "mcp-session-id", "last-event-id"}
    }
    # Preserve the client's Authorization header: the local MCP server remains
    # the authority. The relay never grants MCP access merely from device id.
    req = urllib.request.Request(
        f"http://127.0.0.1:{config.MCP_PORT}{path}", data=raw if raw else None,
        method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read()
            out_headers = {
                k.lower(): v for k, v in response.headers.items()
                if k.lower() in {"content-type", "mcp-session-id", "cache-control"}
            }
            return RelayResponse(response.status, out_headers, body)
    except urllib.error.HTTPError as exc:
        return RelayResponse(exc.code, {"content-type": exc.headers.get("content-type", "text/plain")}, exc.read())


async def run_forever() -> None:
    """Maintain the outbound relay WebSocket, reconnecting with backoff."""
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("relay mode requires the 'websockets' package") from exc

    device_id, secret = ensure_identity()
    url = websocket_url(device_id, secret)
    backoff = 1
    while True:
        try:
            async with websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {secret}"},
                ping_interval=25,
                ping_timeout=20,
                max_size=2 * 1024 * 1024,
            ) as ws:
                backoff = 1
                async for raw in ws:
                    message = json.loads(raw)
                    if message.get("type") != "request" or not message.get("id"):
                        continue
                    request_id = message["id"]
                    try:
                        response = await asyncio.to_thread(_local_request, message)
                        envelope = {
                            "type": "response", "id": request_id,
                            "status": response.status, "headers": response.headers,
                            "body": base64.b64encode(response.body).decode("ascii"),
                        }
                    except Exception as exc:
                        envelope = {
                            "type": "response", "id": request_id, "status": 502,
                            "headers": {"content-type": "text/plain"},
                            "body": base64.b64encode(f"local MCP error: {exc}".encode()).decode("ascii"),
                        }
                    await ws.send(json.dumps(envelope, separators=(",", ":")))
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main() -> None:
    asyncio.run(run_forever())

if __name__ == "__main__":
    main()
