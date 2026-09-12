"""User-owned permission policy for MCP tools.

The policy is deliberately small and predictable. ``standard`` preserves the
project's historical command confirmation behavior; ``full`` trusts the AI
with the same commands the Termux user can run; ``read-only`` exposes only
non-mutating inspection tools.
"""

from . import config

MODES = {
    "read-only": "查看信息和文件，不允许修改或执行命令",
    "standard": "允许日常操作，高风险命令仍需确认",
    "full": "允许完整 Termux 控制，不重复确认命令风险",
}

_READ_ONLY_CAPABILITIES = {
    "filesystem.read",
    "device.read",
    "permissions.read",
    "managed.list",
}


def current_mode() -> str:
    return config.PERMISSION_MODE


def status() -> dict:
    mode = current_mode()
    return {
        "mode": mode,
        "description": MODES[mode],
        "full_control": mode == "full",
        "change_command": "termux-mcp permissions set <read-only|standard|full>",
    }


def allows(capability: str) -> bool:
    mode = current_mode()
    if mode in ("standard", "full"):
        return True
    return capability in _READ_ONLY_CAPABILITIES


def denied(capability: str) -> dict:
    return {
        "error": "permission_denied",
        "capability": capability,
        "permission_mode": current_mode(),
        "message": (
            "The device owner has not enabled this capability. "
            "Change it locally with: termux-mcp permissions set standard (or full)"
        ),
    }
