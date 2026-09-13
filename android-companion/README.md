# Walnut Android Bridge

Experimental Android companion for Termux-MCP. It intentionally starts tiny: an AccessibilityService plus a local app UI that sends the device owner to Android's accessibility settings.

The service already contains the primitive actions we want the future authenticated loopback API to expose: re-resolved click-by-text, focused text replacement, and swipe gestures. No network server is enabled yet; localhost authentication is designed before transport is opened.

See `../docs/ANDROID_BRIDGE_RESEARCH.md` for architecture, security decisions, references, and licensing notes.
