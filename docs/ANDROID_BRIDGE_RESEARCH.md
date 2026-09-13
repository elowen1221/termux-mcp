# Android bridge research notes

This document records the design direction for giving Termux-MCP narrow Android UI control without requiring root or a permanent ADB/Wi-Fi connection.

## What we learned

### Accessibility should be the default UI backend

Android `AccessibilityService` can expose the active window tree and perform node/global actions such as click, set text, back/home/recents, scroll, and gestures. This avoids relying on `pm`/`cmd package` from the Termux app UID, which can be blocked by OEM user/profile isolation.

For app discovery, an Android companion app can query launchable activities through `PackageManager`. On Android 11+, package visibility should be declared with narrow `<queries>` entries rather than requesting broad `QUERY_ALL_PACKAGES` access.

### Keep transport separate from device actions

The strongest pattern in the projects studied is:

```
transport (HTTP / MCP / intent)
        -> command core
        -> accessibility service
        -> Android framework APIs
```

The command core should be transport-agnostic. This lets Termux-MCP talk to the bridge over localhost HTTP first, while leaving room for direct MCP or intent surfaces later.

### Read structure before pixels

The accessibility tree should be the primary observation surface. It is cheaper and easier for an agent to reason about than screenshots. Useful node fields are text, content description, resource id, class, bounds/center, visibility, and supported actions.

Filtering should happen on-device before serialization (`interactive`, `text`, `visible`, app/package filters). Screenshots should remain a fallback for visually meaningful UI that accessibility cannot describe well.

### Re-resolve before acting

Do not trust stale coordinates from an old tree. A command such as `click(text=...)` or `click(id=...)` should resolve the node again immediately before invoking the action. Coordinate taps remain available as an escape hatch.

### Localhost is not authentication

Any app on the phone can usually reach a localhost socket. A bridge therefore needs a real secret/token gate even when bound only to `127.0.0.1`.

Recommended security model:

- accessibility service must be explicitly enabled by the device owner;
- server binds to loopback by default;
- every client gets a revocable token;
- separate capability classes: read UI, interact, type, launch, screenshot/package discovery;
- optional per-app grants;
- a visible foreground-service notification while the bridge is serving;
- one obvious global kill switch.

## Proposed Termux-MCP architecture

```
ChatGPT / MCP client
        |
        v
Termux-MCP
        |
        v
android_bridge (stable narrow API)
   |            |             |
   |            |             +-- MacroDroid (optional fixed macros)
   |            +---------------- Shizuku/rish (optional shell backend)
   +----------------------------- Accessibility companion (default UI backend)
```

The high-level MCP tool names should remain backend-independent. A user should not have to know which backend handled an operation.

### Phase 1

- `android_status`
- `android_list_apps`
- `android_find_app`
- `android_open_app`
- `android_current_ui`
- `android_find_node`
- `android_click`
- `android_back`
- `android_type`
- `android_swipe`

### Phase 2

- wait for UI change / node appearance;
- screenshot fallback;
- current package/activity;
- MacroDroid macro dispatch;
- optional Shizuku/rish capability escalation for package/system operations that Accessibility cannot perform.

## Projects studied

- **khimaros/mimic** — GPL-3.0. Particularly useful for its transport-independent command core, per-client token model, fine-grained permissions, compact accessibility-tree filtering, and localhost HTTP/MCP surfaces.
- **KarryViber/orb-eye** — README states MIT, but the checked-out repository currently has no top-level `LICENSE` file. Treat it as architecture/reference material only unless licensing is clarified. Its single-service implementation is useful for understanding a minimal accessibility + local HTTP design.
- **dondetir/NeuralBridge_mcp** — Apache-2.0. Useful reference for a larger Android companion with explicit gesture, input, UI-tree, screenshot and MCP modules.
- **RikkaApps/Shizuku / Shizuku-API rish** — optional privileged backend for shell/system operations; not required for the primary accessibility path.

No source code from these projects is copied into Termux-MCP by this research work. When ideas influence our design, attribution stays in the project documentation. If code is ever reused, its license and notices must be handled explicitly before merging.

## Current decision

Use AccessibilityService as the default "eyes and hands" backend. Keep Shizuku/rish as an optional higher-privilege backend rather than a prerequisite. MacroDroid remains an optional executor for user-defined deterministic workflows.
