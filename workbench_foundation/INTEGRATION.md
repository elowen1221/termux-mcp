# Integration plan

## Principle

Workbench Foundation is an AI-facing organization layer, not another beginner setup wizard.
Do not overload `termux-mcp setup` or the human screenshot-oriented `termux-mcp guide` with workspace internals.

## Smallest public integration

1. Keep installation responsible only for creating the foundation and local note files.
2. Expose one compact AI-facing entry operation that returns: RULES -> USER -> HANDOFF -> compact map.
3. Expose box creation/checkpoint/doctor as explicit operations rather than hidden filesystem conventions.
4. Keep `USER.md` and `HANDOFF.md` local-only; ship templates only.
5. Do not make the AI scan the whole workspace on connection.

## Why not `guide`

The existing guide is deliberately a screenshot-friendly human cheat sheet for connection/status/recovery. Workbench context has a different audience and lifecycle. Mixing them would make both worse.
