"""Version marker for persistent Termux-MCP configuration semantics.

Schema 1 describes the existing key=value config.env format at the moment the
release lifecycle was introduced. Future incompatible persistent-config changes
must bump this number and provide a tested migration before release.
"""
CONFIG_SCHEMA_VERSION = 1
