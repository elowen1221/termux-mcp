"""Update manifest model: separates persistent rollback data from runtime state."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from .config_schema import CONFIG_SCHEMA_VERSION

@dataclass(frozen=True)
class UpdateManifest:
    from_version: str
    to_version: str
    from_config_schema: int
    to_config_schema: int
    rollback_paths: tuple[str,...]
    ephemeral_paths: tuple[str,...]
    migration: str|None = None

    def validate(self):
        errors=[]
        overlap=set(self.rollback_paths)&set(self.ephemeral_paths)
        if overlap: errors.append('paths cannot be both rollback and ephemeral: '+', '.join(sorted(overlap)))
        if self.to_config_schema < self.from_config_schema: errors.append('config schema downgrade requires an explicit downgrade policy')
        if self.to_config_schema != self.from_config_schema and not self.migration: errors.append('config schema change requires a migration hook')
        if not self.to_version or self.to_version==self.from_version: errors.append('target version must differ from installed version')
        return errors

    def to_json(self): return json.dumps(asdict(self),indent=2)+'\n'

DEFAULT_ROLLBACK_PATHS=(
    '~/.config/termux-mcp/config.env',
    '~/.config/termux-mcp/oauth_state.json',
)
DEFAULT_EPHEMERAL_PATHS=(
    '~/.local/state/termux-mcp/server.pid',
    '~/.local/state/termux-mcp/tunnel.pid',
    '~/.local/state/termux-mcp/server.log',
    '~/.local/state/termux-mcp/tunnel.log',
    '~/.local/state/termux-mcp/public_url',
    '~/.local/state/termux-mcp/last_public_url',
)

def make_manifest(from_version,to_version,to_schema=CONFIG_SCHEMA_VERSION,migration=None):
    return UpdateManifest(from_version,to_version,CONFIG_SCHEMA_VERSION,to_schema,DEFAULT_ROLLBACK_PATHS,DEFAULT_EPHEMERAL_PATHS,migration)
