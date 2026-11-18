# Walnut Android Bridge

Experimental Android companion for Termux-MCP. It intentionally starts tiny: an AccessibilityService plus a local app UI that sends the device owner to Android's accessibility settings.

The service already contains the primitive actions we want the future authenticated loopback API to expose: re-resolved click-by-text, focused text replacement, and swipe gestures. No network server is enabled yet; localhost authentication is designed before transport is opened.

See `../docs/ANDROID_BRIDGE_RESEARCH.md` for architecture, security decisions, references, and licensing notes.


## Nocturne Mobile Capture v1: deeper Compose trees

The Android Accessibility UI endpoint now accepts max_depth up to 40, with
an absolute traversal cap of 1024 nodes. Its response root includes
truncated and visited_nodes fields; clients must refuse capture selection
when truncated is true. The older default of six levels remains unchanged.

ChatGPT's Compose UI can have more than 12 layers of empty layout nodes,
so the old 12-level ceiling did not expose message text in live testing.
This is still an opt-in foreground-only capture path; no background
surveillance, automatic uploading, or direct memory writes are added.

The companion version is 0.5.14 (code 35). Install only through an APK
signed with the same certificate as the currently installed application.
A mismatched older keystore must never be used to replace the installed
app. The original stable-signing CI workflow is the preferred packaging
route; do not publish test-branch artifacts as rolling stable releases.


## Read-only bounded text scan (0.5.15)

ChatGPT Android's Compose hierarchy has more than 40 nested view levels on the
tested screen. The old full-tree endpoint still has a 40-level depth ceiling.
The new authenticated localhost POST /v1/text-nodes endpoint is intended for
explicit human-reviewed capture, not bulk scraping.

The scan traverses up to 128 levels and 2048 nodes, but returns only up to
128 non-editable text candidates with original child-index paths and class
names, capped to 131072 combined text characters. It omits editable fields and
all their descendants. A truncated flag is set if any limit is reached;
Nocturne refuses to submit a partial scan. It does not infer who wrote a message,
automatically upload, capture in the background, or create durable memory.

Install this build only with the matching signing identity and without
uninstalling the existing app. Re-enabling Accessibility may be necessary after
a package update. Do not use this endpoint as a replacement for explicit
consent and user-role confirmation.
