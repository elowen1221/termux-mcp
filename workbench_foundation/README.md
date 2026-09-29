# Workbench Foundation

A thin organization layer for long-lived AI workspaces.

The workbench defines only stable top-level categories and handoff rules. Individual machines and their AI create their own boxes underneath those categories. Runtime behavior lives in `termux_mcp.workbench`; this directory contains the public contract and templates installed into a local workbench.

## Entry order

An AI should read, in order:

1. `RULES.md` — rules shipped by the workbench.
2. `USER.md` — durable local preferences owned by the user.
3. `HANDOFF.md` — short current-state note written by the local AI for its next session.
4. the compact box map; then a box `README.md` only when entering that box.

Only templates for USER and HANDOFF are shipped. Their live copies are local state.

## Box contract

Every persistent box has a `README.md` describing current truth. Historical detail belongs in `LOG.md`. The foundation owns categories and conventions, not user projects.
