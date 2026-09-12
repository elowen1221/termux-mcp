"""Plan and apply project-local URL changes when the public base domain moves.

Cloudflare ingress/DNS is handled by :mod:`termux_mcp.named_tunnel`. This
module handles the second half: known text configuration/code files in the
Termux-MCP workbench. It is intentionally conservative: only explicitly
listed files are touched, secrets are never printed, and every changed file
gets a timestamped backup before replacement.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HOME = Path(os.path.expanduser("~"))
PROJECT_ROOT = HOME / "Termux-MCP"


@dataclass(frozen=True)
class RewriteTarget:
    path: Path
    required: bool = False


@dataclass(frozen=True)
class RewritePlan:
    path: Path
    replacements: int
    secret: bool


def _default_targets(project_root: Path = PROJECT_ROOT, home: Path = HOME) -> list[RewriteTarget]:
    """Known files that may contain public service URLs."""
    return [
        RewriteTarget(home / ".config" / "termux-mcp" / "config.env"),
        RewriteTarget(home / ".config" / "termux-mcp" / "alpaca.env"),
        RewriteTarget(home / ".config" / "termux-mcp" / "alpaca-oauth.env"),
        RewriteTarget(home / ".config" / "termux-mcp-weather" / "config.env"),
        RewriteTarget(project_root / "local_extensions" / "start-walnut-stack.sh", required=True),
        RewriteTarget(project_root / "local_extensions" / "weather_mcp" / "start.sh", required=True),
        RewriteTarget(project_root / "local_extensions" / "weather_mcp" / "server.py", required=True),
        RewriteTarget(project_root / "local_extensions" / "alpaca_mcp" / "server.py", required=True),
    ]


def _is_secret(path: Path, home: Path = HOME) -> bool:
    try:
        path.relative_to(home / ".config")
        return True
    except ValueError:
        return False


def _validate_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        domain,
    ):
        raise ValueError(f"invalid domain: {value!r}")
    return domain


def _domain_pattern(old_domain: str) -> re.Pattern[str]:
    old = _validate_domain(old_domain)
    escaped = re.escape(old)
    # Match the base domain and any subdomains, but not a larger hostname such
    # as notexample.com when the intended base is example.com.
    return re.compile(
        rf"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)*{escaped}(?![A-Za-z0-9.-])",
        re.IGNORECASE,
    )


def plan_url_rewrites(
    old_domain: str,
    new_domain: str,
    *,
    targets: Iterable[RewriteTarget] | None = None,
    project_root: Path = PROJECT_ROOT,
    home: Path = HOME,
) -> list[RewritePlan]:
    """Return a safe summary of known files that would change."""
    old = _validate_domain(old_domain)
    new = _validate_domain(new_domain)
    if old == new:
        raise ValueError("old and new domains must be different")
    pattern = _domain_pattern(old)
    plans: list[RewritePlan] = []
    selected = list(targets) if targets is not None else _default_targets(project_root, home)
    for target in selected:
        path = target.path
        if not path.exists():
            if target.required:
                raise FileNotFoundError(f"required migration target is missing: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        count = sum(1 for _ in pattern.finditer(text))
        if count:
            plans.append(RewritePlan(path=path, replacements=count, secret=_is_secret(path, home)))
    return plans


def apply_url_rewrites(
    old_domain: str,
    new_domain: str,
    *,
    targets: Iterable[RewriteTarget] | None = None,
    project_root: Path = PROJECT_ROOT,
    home: Path = HOME,
) -> list[tuple[RewritePlan, str]]:
    """Rewrite known files atomically, backing up every changed file."""
    old = _validate_domain(old_domain)
    new = _validate_domain(new_domain)
    plans = plan_url_rewrites(
        old,
        new,
        targets=targets,
        project_root=project_root,
        home=home,
    )
    pattern = _domain_pattern(old)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results: list[tuple[RewritePlan, str]] = []
    for plan in plans:
        path = plan.path
        original = path.read_text(encoding="utf-8")

        def repl(match: re.Match[str]) -> str:
            host = match.group(0)
            prefix = host[: -len(old)]
            return prefix + new

        updated, count = pattern.subn(repl, original)
        if count != plan.replacements:
            raise RuntimeError(f"rewrite count changed while applying: {path}")
        backup = str(path) + f".before-domain-{stamp}"
        shutil.copy2(path, backup)
        mode = path.stat().st_mode & 0o777
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(updated)
            os.chmod(temp_name, mode)
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        results.append((plan, backup))
    return results
