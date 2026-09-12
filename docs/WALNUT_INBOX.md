# Walnut Event Inbox

Walnut Inbox is the durable event bus between local services and an assistant
run. It does **not** wake ChatGPT by itself. A ChatGPT scheduled task can act as
the heartbeat: wake periodically, read pending events, verify important events
with their source MCP, handle them, then acknowledge them.

## Local endpoint

`http://127.0.0.1:8794/mcp`

The first version intentionally stays local-only. It does not need another
public Cloudflare route: local producers write events directly, while the
assistant can initially inspect the inbox through the Termux execution layer.
A dedicated authenticated public MCP route can be added later if it materially
improves the scheduled-task integration.

## MCP tools

- `push_event` — append a structured event; optional `dedupe_key` makes retries idempotent.
- `list_events` — list pending/acknowledged/archived/all events.
- `get_event` — inspect one event.
- `ack_event` — mark a handled event acknowledged.
- `archive_event` — retain history while removing it from active work.
- `inbox_status` — counts and local storage status.

Priorities are `low`, `normal`, `high`, and `urgent`. Payloads are capped at
64 KiB. The SQLite database is stored at
`~/.local/state/termux-mcp/walnut-inbox/events.sqlite3` with mode 0600.

## Producer helper

Local scripts do not need to speak MCP. They can emit an event with:

`python local_extensions/walnut_inbox/emit.py SOURCE TYPE TITLE --priority normal --payload '{"key":"value"}' --dedupe-key UNIQUE_KEY`

Use a stable dedupe key for retries of the same real-world event.

## Processing rule

Inbox events are signals, not automatically trusted facts. For consequential
actions, use the source system as ground truth. Example: an
`alpaca.order_filled` event should cause the assistant to query Alpaca for the
actual order/fill before recording a review or taking another trading action.

## Wake-up bridge

Current practical design:

1. Gmail/Alpaca/Weather/Termux/worker scripts write events locally.
2. ChatGPT Scheduled Task wakes the assistant periodically (hourly is suitable
   for the first version).
3. The assistant reads pending events and handles relevant work.
4. The assistant acknowledges handled events.
5. Truly urgent local events may additionally use an Android notification so a
   one-hour ChatGPT polling delay is not safety-critical.

If custom webhook-triggered ChatGPT tasks become available later, replace the
periodic heartbeat with a direct trigger; the inbox schema and producers do not
need to change.
