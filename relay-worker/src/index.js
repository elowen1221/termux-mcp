import { DurableObject } from "cloudflare:workers";

const ID_RE = /^[a-z0-9-]{12,64}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let match = url.pathname.match(/^\/connect\/([a-z0-9-]+)$/);
    if (match) return routeDevice(env, match[1], request);
    match = url.pathname.match(/^\/d\/([a-z0-9-]+)(\/mcp(?:\/.*)?)$/);
    if (match) {
      const forwarded = new Request(new URL(match[2], url.origin), request);
      return routeDevice(env, match[1], forwarded);
    }
    if (url.pathname === "/health") return Response.json({ ok: true, service: "termux-mcp-relay" });
    return new Response("not found", { status: 404 });
  }
};

function routeDevice(env, id, request) {
  if (!ID_RE.test(id)) return new Response("invalid device id", { status: 400 });
  const stub = env.DEVICES.get(env.DEVICES.idFromName(id));
  return stub.fetch(request);
}

export class DeviceRelay extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.ctx = ctx;
    this.pending = new Map();
  }

  async fetch(request) {
    if (request.headers.get("Upgrade") === "websocket") return this.connect(request);
    return this.proxy(request);
  }

  async connect(request) {
    const supplied = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
    if (!supplied || supplied.length < 32) return new Response("unauthorized", { status: 401 });
    const digest = await sha256(supplied);
    const stored = await this.ctx.storage.get("secretHash");
    if (stored && stored !== digest) return new Response("unauthorized", { status: 401 });
    if (!stored) await this.ctx.storage.put("secretHash", digest);

    for (const old of this.ctx.getWebSockets()) old.close(4001, "replaced by newer device connection");
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({ role: "device" });
    return new Response(null, { status: 101, webSocket: client });
  }

  async proxy(request) {
    const sockets = this.ctx.getWebSockets();
    if (!sockets.length) return new Response("device offline", { status: 503 });
    const ws = sockets[0];
    const id = crypto.randomUUID();
    const body = request.body ? await request.arrayBuffer() : new ArrayBuffer(0);
    if (body.byteLength > 1024 * 1024) return new Response("request too large", { status: 413 });
    const headers = {};
    for (const name of ["content-type", "accept", "authorization", "mcp-session-id", "last-event-id"]) {
      const value = request.headers.get(name); if (value) headers[name] = value;
    }
    const envelope = JSON.stringify({
      type: "request", id, method: request.method,
      path: new URL(request.url).pathname + new URL(request.url).search,
      headers, body: arrayBufferToBase64(body)
    });
    const responsePromise = new Promise((resolve) => {
      const timer = setTimeout(() => { this.pending.delete(id); resolve(new Response("device timeout", { status: 504 })); }, 125000);
      this.pending.set(id, { resolve, timer });
    });
    ws.send(envelope);
    return responsePromise;
  }

  webSocketMessage(ws, raw) {
    let message;
    try { message = JSON.parse(typeof raw === "string" ? raw : new TextDecoder().decode(raw)); } catch { return; }
    if (message.type !== "response" || !message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    clearTimeout(pending.timer); this.pending.delete(message.id);
    pending.resolve(new Response(base64ToUint8(message.body || ""), {
      status: Number(message.status) || 502, headers: message.headers || {}
    }));
  }

  webSocketClose(ws, code, reason) { ws.close(code, reason); }
  webSocketError() {}
}

async function sha256(text) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, "0")).join("");
}
function arrayBufferToBase64(buffer) {
  let s = ""; for (const b of new Uint8Array(buffer)) s += String.fromCharCode(b); return btoa(s);
}
function base64ToUint8(text) {
  const s = atob(text); const out = new Uint8Array(s.length); for (let i=0;i<s.length;i++) out[i]=s.charCodeAt(i); return out;
}
