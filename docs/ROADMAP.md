# Development roadmap

This roadmap prioritizes the gap between “the server works” and “a new user can
reliably operate it.” Checked items describe the current `main` baseline plus
local work that is ready for review.

## 0.9 — current foundation

- [x] Streamable HTTP MCP endpoint and REST API
- [x] shared operations layer
- [x] bearer authentication and persistent OAuth state
- [x] workspace and symlink escape protection
- [x] command risk classification and write snapshots
- [x] server/tunnel lifecycle commands
- [x] profile isolation
- [x] multi-provider tunnel fallback
- [x] pip-based installer and live MCP smoke test
- [x] zero-to-running bootstrap entry point

## 0.10 — installation and repair

- [x] add a one-time guided setup for ChatGPT, Claude, and Grok
- [x] add owner-selectable read-only, standard, and full permission modes
- [x] import remote MCP URLs and common Python/Node.js GitHub MCP projects
- [x] expose AI-facing managed-MCP install/list/inspect/call/remove tools
- [x] add `termux-mcp doctor --json` with stable check identifiers
- [x] validate profiles, ports, timeouts, and output limits before startup
- [x] preserve installer output in an actionable local log
- [x] run tests and critical static checks in GitHub Actions
- [ ] add targeted repair suggestions for package, PATH, port, tunnel, and permission failures
- [ ] add `termux-mcp update` with clean-tree checks and post-update rollback
- [ ] add an uninstall command that preserves user configuration by default
- [ ] verify bootstrap behavior on interrupted and repeated installations
- [ ] test F-Droid and GitHub Termux builds on Android 12, 14, and 16

## 0.11 — connection experience

- [ ] generate client-specific connection snippets without printing secrets
- [ ] add a local pairing page or QR handoff for the public MCP URL
- [x] add safe base-domain migration planning, backups, ingress validation, local URL rewrites, and public route health checks
- [ ] make domain migration update/re-authorize every supported OAuth client automatically where the provider permits it
- [ ] add optional Termux:Boot integration
- [ ] add battery-optimization and background-process diagnostics

## 1.0 — stable release gate

- [ ] documented configuration migrations
- [ ] reproducible tagged releases with checksums
- [ ] automated clean-device installation tests
- [ ] threat-model and exposed-tool review
- [ ] compatibility matrix for major MCP clients
- [ ] recovery guide covering token rotation, tunnel failure, and corrupted state
