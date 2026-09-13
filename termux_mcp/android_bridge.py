"""Small Android control bridge with an optional Shizuku/rish backend.

The bridge deliberately exposes narrow operations instead of a second raw
shell.  Ordinary Termux is used for capability probes; rish is preferred for
package/activity operations once the device owner has configured Shizuku.
"""
from __future__ import annotations

import re
import base64
import os
from pathlib import Path
import json
import urllib.request
import urllib.error
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    returncode: int


def _run(argv: list[str], timeout: float = 8.0) -> ExecResult:
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return ExecResult(p.stdout, p.stderr, p.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ExecResult("", str(exc), 127)


ACCESSIBILITY_URL = "http://127.0.0.1:8766"

def _accessibility_token() -> str | None:
    value = os.environ.get("WALNUT_ANDROID_TOKEN", "").strip()
    if value:
        return value
    token_file = Path.home() / ".config" / "termux-mcp" / "android-token"
    try:
        value = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None

def _accessibility(path: str, payload: dict | None = None) -> dict | None:
    token = _accessibility_token()
    if not token:
        return None
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(ACCESSIBILITY_URL + path, data=data, headers={"Content-Type": "application/json", "X-Walnut-Token": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=1.5) as response:
            return json.loads(response.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None

def current_ui(max_depth: int = 6) -> dict:
    data = _accessibility("/v1/ui", {"max_depth": max_depth})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def screenshot_png() -> bytes | None:
    data = _accessibility("/v1/screenshot")
    if not data or not data.get("ok"):
        return None
    payload = data.get("data", {})
    encoded = payload.get("base64")
    if not isinstance(encoded, str):
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None

def click(text: str) -> dict:
    data = _accessibility("/v1/click", {"text": text})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def type_text(text: str) -> dict:
    data = _accessibility("/v1/type", {"text": text})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def swipe(x1: float, y1: float, x2: float, y2: float, duration: int = 300) -> dict:
    data = _accessibility("/v1/swipe", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def back() -> dict:
    data = _accessibility("/v1/back")
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def _rish() -> str | None:
    return shutil.which("rish")


def _remote(command: str) -> ExecResult:
    rish = _rish()
    if not rish:
        return ExecResult("", "rish is not installed/configured", 127)
    return _run([rish, "-c", command])


def status() -> dict:
    companion = _accessibility("/v1/status")
    if companion and companion.get("ok"):
        data = companion.get("data", {})
        return {"backend": "accessibility", "accessibility_ready": bool(data.get("accessibility")), "version": data.get("version"), "port": data.get("port"), "next": None if data.get("accessibility") else "Enable Walnut Android Bridge in Android accessibility settings."}
    rish = _rish()
    result = _remote("id") if rish else None
    ready = bool(result and result.returncode == 0 and "uid=2000" in result.stdout)
    return {
        "backend": "shizuku-rish" if rish else "termux-only",
        "rish_installed": bool(rish),
        "shell_uid_ready": ready,
        "identity": result.stdout.strip() if result and result.returncode == 0 else None,
        "next": None if ready else "Start Shizuku, export rish to Termux, then retry android_status.",
    }


def list_apps(filter: str = "", third_party_only: bool = True) -> dict:
    companion = _accessibility("/v1/apps")
    if companion and companion.get("ok"):
        apps = companion.get("data", [])
        if filter:
            needle = filter.casefold()
            apps = [app for app in apps if needle in str(app.get("label", "")).casefold() or needle in str(app.get("package", "")).casefold()]
        return {"apps": apps, "count": len(apps), "backend": "accessibility"}
    flag = " -3" if third_party_only else ""
    result = _remote(f"pm list packages{flag}")
    if result.returncode != 0:
        return {"apps": [], "error": result.stderr.strip(), "status": status()}
    names = [line.removeprefix("package:").strip() for line in result.stdout.splitlines() if line.startswith("package:")]
    if filter:
        needle = filter.casefold()
        names = [name for name in names if needle in name.casefold()]
    return {"apps": names, "count": len(names), "backend": "shizuku-rish"}


def find_app(query: str) -> dict:
    query = query.strip()
    if not query:
        return {"matches": [], "error": "query is required"}
    data = list_apps(filter=query, third_party_only=False)
    return {"query": query, "matches": data.get("apps", []), "backend": data.get("backend"), "status": data.get("status")}


def open_app(package: str) -> dict:
    package = package.strip()
    companion = _accessibility("/v1/open", {"query": package})
    if companion and companion.get("ok"):
        app = companion.get("data", {})
        return {"opened": True, "package": app.get("package"), "label": app.get("label"), "backend": "accessibility"}
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", package):
        return {"opened": False, "error": "app name was not found by the accessibility companion and is not a package id"}
    # cmd package resolve-activity gives us a concrete component when available.
    resolved = _remote(
        "cmd package resolve-activity --brief -a android.intent.action.MAIN "
        f"-c android.intent.category.LAUNCHER {package}"
    )
    component = resolved.stdout.strip().splitlines()[-1] if resolved.returncode == 0 and resolved.stdout.strip() else ""
    if "/" not in component:
        return {"opened": False, "package": package, "error": resolved.stderr.strip() or "launcher activity not found"}
    started = _remote(f"am start -n {component}")
    return {
        "opened": started.returncode == 0,
        "package": package,
        "component": component,
        "stdout": started.stdout.strip(),
        "error": started.stderr.strip() or None,
    }
