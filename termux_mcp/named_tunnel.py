"""Safe management for Cloudflare named-tunnel ingress rules."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

DEFAULT_CONFIG = os.path.expanduser("~/.cloudflared/config.yml")


@dataclass(frozen=True)
class IngressRule:
    hostname: str
    service: str


def _hostname(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        host,
    ):
        raise ValueError("invalid hostname")
    return host


def _port(value: int) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    return port


def list_ingress(path: str = DEFAULT_CONFIG) -> List[IngressRule]:
    rules: List[IngressRule] = []
    pending: Optional[str] = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- hostname:"):
            pending = line.split(":", 1)[1].strip()
        elif pending and line.startswith("service:"):
            rules.append(IngressRule(pending, line.split(":", 1)[1].strip()))
            pending = None
    return rules



def _base_domain(value: str) -> str:
    """Validate a base domain used for bulk hostname migration.

    This intentionally accepts ordinary DNS names only. It does not try to
    consult the public suffix list; callers explicitly choose the domain they
    own (for example ``example.com``).
    """
    return _hostname(value)


def plan_domain_migration(
    new_domain: str,
    *,
    path: str = DEFAULT_CONFIG,
    from_domain: str | None = None,
) -> List[tuple[IngressRule, IngressRule]]:
    """Return old/new ingress pairs without changing any files.

    ``from_domain`` is optional when every configured hostname shares one
    obvious suffix. For mixed-domain configurations, require it explicitly so
    a migration cannot accidentally rewrite unrelated routes.
    """
    new_base = _base_domain(new_domain)
    rules = list_ingress(path)
    if not rules:
        return []

    if from_domain:
        old_base = _base_domain(from_domain)
    else:
        labels = [rule.hostname.lower().rstrip('.').split('.') for rule in rules]
        common: list[str] = []
        for parts in zip(*(reversed(x) for x in labels)):
            if len(set(parts)) != 1:
                break
            common.append(parts[0])
        if len(common) < 2:
            raise ValueError(
                "could not infer one source domain from mixed ingress routes; "
                "pass --from-domain"
            )
        old_base = '.'.join(reversed(common))

    planned: List[tuple[IngressRule, IngressRule]] = []
    for rule in rules:
        host = rule.hostname.lower().rstrip('.')
        if host == old_base:
            prefix = ''
        elif host.endswith('.' + old_base):
            prefix = host[: -(len(old_base) + 1)]
        else:
            continue
        new_host = new_base if not prefix else f"{prefix}.{new_base}"
        planned.append((rule, IngressRule(new_host, rule.service)))

    if not planned:
        raise ValueError(f"no ingress routes belong to {old_base}")
    return planned


def migrate_ingress_domain(
    new_domain: str,
    *,
    path: str = DEFAULT_CONFIG,
    from_domain: str | None = None,
    validate: bool = True,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[str, List[tuple[IngressRule, IngressRule]]]:
    """Atomically rewrite ingress hostnames to a new base domain.

    The Cloudflare config is backed up before replacement and restored if
    ``cloudflared tunnel ingress validate`` rejects the result. DNS routing is
    deliberately separate; callers can preview first and create DNS records
    only after the config is known-good.
    """
    target = Path(path)
    original = target.read_text(encoding="utf-8")
    planned = plan_domain_migration(
        new_domain, path=path, from_domain=from_domain
    )
    updated = original
    for old, new in planned:
        pattern = re.compile(
            r"(^\s*-\s*hostname:\s*)" + re.escape(old.hostname) + r"(\s*$)",
            re.MULTILINE,
        )
        updated, count = pattern.subn(
            lambda match: match.group(1) + new.hostname + match.group(2),
            updated,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"could not rewrite ingress hostname: {old.hostname}")

    if updated == original:
        return "", planned

    backup = str(target) + ".before-domain-" + time.strftime("%Y%m%d-%H%M%S")
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.chmod(temp_name, 0o600)
        shutil.copy2(target, backup)
        os.replace(temp_name, target)
        if validate:
            result = runner(
                ["cloudflared", "tunnel", "ingress", "validate"],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                shutil.copy2(backup, target)
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(
                    f"invalid Cloudflare ingress; restored backup: {detail}"
                )
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return backup, planned

def add_ingress(
    hostname: str,
    port: int,
    *,
    path: str = DEFAULT_CONFIG,
    validate: bool = True,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    host = _hostname(hostname)
    port = _port(port)
    target = Path(path)
    original = target.read_text(encoding="utf-8")
    rules = list_ingress(path)
    for rule in rules:
        if rule.hostname == host:
            expected = f"http://127.0.0.1:{port}"
            if rule.service == expected:
                return ""
            raise ValueError(f"{host} already routes to {rule.service}")

    catch = "  - service: http_status:404"
    if catch not in original:
        raise RuntimeError("Cloudflare config has no final http_status:404 rule")
    addition = (
        f"  - hostname: {host}\n"
        f"    service: http://127.0.0.1:{port}\n"
    )
    updated = original.replace(catch, addition + catch, 1)
    backup = str(target) + ".before-" + time.strftime("%Y%m%d-%H%M%S")

    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(updated)
        os.chmod(temp_name, 0o600)
        shutil.copy2(target, backup)
        os.replace(temp_name, target)
        if validate:
            result = runner(
                ["cloudflared", "tunnel", "ingress", "validate"],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                shutil.copy2(backup, target)
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"invalid Cloudflare ingress; restored backup: {detail}")
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return backup


def route_dns(
    tunnel: str,
    hostname: str,
    *,
    retries: int = 3,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> subprocess.CompletedProcess:
    host = _hostname(hostname)
    last: Optional[subprocess.CompletedProcess] = None
    for attempt in range(max(1, retries)):
        last = runner(
            ["cloudflared", "tunnel", "route", "dns", tunnel, host],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        combined = (last.stdout or "") + "\n" + (last.stderr or "")
        if last.returncode == 0 or "already exists" in combined.lower():
            return last
        if attempt + 1 < retries:
            sleeper(float(2 ** attempt))
    assert last is not None
    detail = (last.stderr or last.stdout).strip()
    raise RuntimeError(f"Cloudflare DNS route failed after {retries} attempts: {detail}")
