"""Small Android control bridge with an optional Shizuku/rish backend.

The bridge deliberately exposes narrow operations instead of a second raw
shell.  Ordinary Termux is used for capability probes; rish is preferred for
package/activity operations once the device owner has configured Shizuku.
"""
from __future__ import annotations

import re
import time
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

def _valid_accessibility_token(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > 256:
        return None
    # Header values must not contain controls/newlines. Pairing tokens are
    # URL-safe Base64, so keep the accepted alphabet deliberately narrow.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return None
    return value

def _accessibility_token() -> str | None:
    value = _valid_accessibility_token(os.environ.get("WALNUT_ANDROID_TOKEN"))
    if value:
        return value
    token_file = Path.home() / ".config" / "termux-mcp" / "android-token"
    try:
        return _valid_accessibility_token(token_file.read_text(encoding="utf-8"))
    except OSError:
        return None

def _accessibility(path: str, payload: dict | None = None, timeout: float = 3.0) -> dict | None:
    token = _accessibility_token()
    if not token:
        return None
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ACCESSIBILITY_URL + path, data=data, headers={"Content-Type": "application/json; charset=utf-8", "X-Walnut-Token": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            if isinstance(body, dict):
                body.setdefault("http_status", exc.code)
                return body
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {"ok": False, "error": f"accessibility HTTP {exc.code}", "http_status": exc.code}
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError):
        return None

def current_context() -> dict:
    data = _accessibility("/v1/context")
    return data or {"ok": False, "error": "accessibility companion unavailable"}

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

def click_retry(text: str, attempts: int = 2, delay_ms: int = 180) -> dict:
    attempts = max(1, min(int(attempts), 4))
    delay_ms = max(0, min(int(delay_ms), 1500))
    history = []
    for attempt in range(1, attempts + 1):
        result = click(text)
        history.append({"attempt": attempt, "result": result})
        if result.get("ok"):
            return {"ok": True, "attempts": attempt, "result": result}
        if attempt < attempts and delay_ms:
            time.sleep(delay_ms / 1000.0)
    return {"ok": False, "error": "click failed after retries", "attempts": attempts, "history": history}

def click(text: str) -> dict:
    data = _accessibility("/v1/click", {"text": text})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def click_selector(*, text: str = "", view_id: str = "", desc: str = "", index: int = 0) -> dict:
    if not any((text.strip(), view_id.strip(), desc.strip())):
        return {"ok": False, "error": "at least one selector is required"}
    data = _accessibility("/v1/click-selector", {"text": text, "view_id": view_id, "desc": desc, "index": int(index)})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def tap(x: float, y: float) -> dict:
    data = _accessibility("/v1/tap", {"x": x, "y": y})
    return data or {"ok": False, "error": "accessibility companion unavailable"}

def wait_for_text(expect_text: str, timeout_ms: int = 2000, max_depth: int = 8) -> dict:
    needle = expect_text.strip().casefold()
    if not needle:
        return {"ok": False, "error": "expect_text is required", "verified": False}
    timeout_ms = max(100, min(int(timeout_ms), 10000))
    deadline = time.monotonic() + timeout_ms / 1000.0
    last_ui = None
    checks = 0
    while time.monotonic() < deadline:
        checks += 1
        last_ui = current_ui(max_depth)
        if needle in json.dumps(last_ui, ensure_ascii=False).casefold():
            return {"ok": True, "verified": True, "expect_text": expect_text, "checks": checks}
        time.sleep(0.15)
    return {"ok": False, "error": "expected text did not appear", "verified": False, "expect_text": expect_text, "checks": checks, "ui": last_ui}

def click_and_verify(text: str, expect_text: str, timeout_ms: int = 2000) -> dict:
    action = click_retry(text, attempts=2, delay_ms=180)
    if not action.get("ok"):
        return {"ok": False, "action": action, "verified": False}
    verification = wait_for_text(expect_text, timeout_ms, 8)
    return {"ok": verification.get("verified", False), "action": action, "verified": verification.get("verified", False), "verification": verification}

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


def _foreground_package() -> str | None:
    context = current_context()
    if not context.get("ok"):
        return None
    data = context.get("data", {})
    package = data.get("package")
    return package if isinstance(package, str) and package not in ("", "null", "None") else None

def _wait_for_package(package: str, timeout_ms: int = 1500) -> bool:
    deadline = time.monotonic() + max(100, min(int(timeout_ms), 5000)) / 1000.0
    while time.monotonic() < deadline:
        if _foreground_package() == package:
            return True
        time.sleep(0.1)
    return False

def gadgetbridge_sync(data_types_hex: str = "0x000003e1") -> dict:
    result = _accessibility("/v1/gadgetbridge/sync", {"dataTypesHex": data_types_hex})
    return result or {"ok": False, "error": "android accessibility bridge unavailable"}

def gadgetbridge_event() -> dict:
    result = _accessibility("/v1/gadgetbridge/event")
    return result or {"ok": False, "error": "android accessibility bridge unavailable"}

def open_app(package: str) -> dict:
    query = package.strip()
    if not query:
        return {"opened": False, "error": "app name or package is required"}

    # Resolve the requested app first. Do not trust only the launch request:
    # the foreground Accessibility context is the final source of truth.
    resolved_package = query if re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", query) else None
    resolved_label = None
    if resolved_package is None:
        apps = list_apps(filter=query, third_party_only=False)
        candidates = [app for app in apps.get("apps", []) if isinstance(app, dict)]
        exact = next((app for app in candidates if str(app.get("label", "")).casefold() == query.casefold()), None)
        if exact is None and len(candidates) == 1:
            exact = candidates[0]
        if exact:
            resolved_package = exact.get("package")
            resolved_label = exact.get("label")

    launch_query = resolved_package or query
    companion = _accessibility("/v1/open", {"query": launch_query}, timeout=8.0)
    if companion and companion.get("ok"):
        app = companion.get("data", {})
        resolved_package = app.get("package") or resolved_package
        resolved_label = app.get("label") or resolved_label

    if resolved_package and _wait_for_package(resolved_package):
        result = {"opened": True, "package": resolved_package, "label": resolved_label, "backend": "accessibility", "verified_foreground": True}
        if query != resolved_package:
            result["resolved_from_label"] = query
        return result

    if not resolved_package:
        return {"opened": False, "error": "app name was not found by the accessibility companion and is not a package id"}

    # Optional privileged fallback for package ids when Accessibility launch
    # could not be verified. Verification still uses foreground context.
    resolved = _remote(
        "cmd package resolve-activity --brief -a android.intent.action.MAIN "
        f"-c android.intent.category.LAUNCHER {resolved_package}"
    )
    component = resolved.stdout.strip().splitlines()[-1] if resolved.returncode == 0 and resolved.stdout.strip() else ""
    if "/" not in component:
        companion_requested = bool(companion and companion.get("ok"))
        return {"opened": False, "package": resolved_package, "error": resolved.stderr.strip() or "launcher activity not found", "verified_foreground": False,
                "launch_requested": companion_requested,
                "limitation": "android_background_activity_start" if companion_requested else None,
                "hint": "Bring the app to foreground manually or configure a privileged launcher such as rish." if companion_requested else None}
    started = _remote(f"am start -n {component}")
    verified = started.returncode == 0 and _wait_for_package(resolved_package)
    companion_requested = bool(companion and companion.get("ok"))
    return {
        "opened": verified, "package": resolved_package, "component": component, "stdout": started.stdout.strip(),
        "error": None if verified else (started.stderr.strip() or "launch was not observed in foreground"), "verified_foreground": verified,
        "launch_requested": companion_requested,
        "limitation": "android_background_activity_start" if (companion_requested and not verified) else None,
        "hint": "Bring the app to foreground manually or configure a privileged launcher such as rish." if (companion_requested and not verified) else None,
    }
