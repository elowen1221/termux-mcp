# Update transaction model

An update is a transaction, not a `git pull`.

## State classes

### Rollback-persistent
These are user-owned durable values. They are snapshotted before an update and restored if installation, migration, or validation fails.

Initial schema-1 set:
- `~/.config/termux-mcp/config.env`
- `~/.config/termux-mcp/oauth_state.json`

Future persistent files must be explicitly classified before a release can modify them.

### Ephemeral runtime
These describe a running process or observation and must not be blindly restored from an old snapshot:
- server/tunnel PID files
- server/tunnel logs
- current/last observed public URL

Runtime state is recreated by start/recovery logic after rollback.

## Manifest contract

Each candidate update has a manifest containing installed/target product versions, source/target config schema, rollback paths, ephemeral paths, and an optional migration hook. A schema change without a migration hook is invalid. A path cannot belong to both state classes.

## Transaction

1. Resolve and validate candidate manifest.
2. Snapshot only rollback-persistent paths.
3. Stop or quiesce affected owned processes when required.
4. Install candidate application bits.
5. Run the declared config migration.
6. Start/reconcile required services.
7. Run protocol-aware validation / doctor.
8. Commit the new known-good version marker.

On failure after step 2, restore rollback-persistent state, discard stale ephemeral runtime state, restore the previous application version, then re-run recovery/doctor. The current prototype implements persistent-state snapshot/restore; application-version restoration and release fetching are intentionally not wired yet.
