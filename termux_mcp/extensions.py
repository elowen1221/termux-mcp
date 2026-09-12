"""Optional local-only MCP extensions.

The public package stays generic. Device-specific/private tools can live in
ignored files and opt in through TERMUX_MCP_LOCAL_EXTENSIONS, a comma-separated
list of Python files. Each file must expose register(mcp, step_tools).
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from . import config

ENV_NAME = "TERMUX_MCP_LOCAL_EXTENSIONS"


def configured_paths() -> list[Path]:
    raw = config._env_or_file(ENV_NAME, "")
    return [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]


def register_local_extensions(mcp, step_tools: dict) -> list[str]:
    loaded: list[str] = []
    for path in configured_paths():
        path = path.resolve()
        if not path.is_file():
            continue
        name = "termux_mcp_local_" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if not callable(register):
            continue
        register(mcp, step_tools)
        loaded.append(str(path))
    return loaded
