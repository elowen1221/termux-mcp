from termux_mcp import android_bridge


def test_status_without_rish(monkeypatch):
    monkeypatch.setattr(android_bridge.shutil, "which", lambda _: None)
    data = android_bridge.status()
    assert data["backend"] == "termux-only"
    assert data["shell_uid_ready"] is False


def test_list_apps_filters(monkeypatch):
    monkeypatch.setattr(android_bridge, "_remote", lambda _: android_bridge.ExecResult("package:com.example.one\npackage:org.other\n", "", 0))
    data = android_bridge.list_apps(filter="example")
    assert data["apps"] == ["com.example.one"]


def test_open_app_rejects_non_package():
    assert android_bridge.open_app("小红书")["opened"] is False

def test_accessibility_probe_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("WALNUT_ANDROID_TOKEN", "")
    assert android_bridge._accessibility_token() is None


def test_list_apps_prefers_accessibility_labels(monkeypatch):
    monkeypatch.setattr(android_bridge, "_accessibility", lambda path, payload=None: {"ok": True, "data": [{"label": "小红书", "package": "com.xingin.xhs"}, {"label": "Chrome", "package": "com.android.chrome"}]} if path == "/v1/apps" else None)
    data = android_bridge.list_apps(filter="小红")
    assert data["backend"] == "accessibility"
    assert data["apps"] == [{"label": "小红书", "package": "com.xingin.xhs"}]


def test_open_app_accepts_human_name_via_companion(monkeypatch):
    monkeypatch.setattr(android_bridge, "_accessibility", lambda path, payload=None: {"ok": True, "data": {"label": "小红书", "package": "com.xingin.xhs"}} if path == "/v1/open" else None)
    data = android_bridge.open_app("小红书")
    assert data["opened"] is True
    assert data["package"] == "com.xingin.xhs"


def test_tap_uses_accessibility(monkeypatch):
    monkeypatch.setattr(android_bridge, "_accessibility", lambda path, payload=None: {"ok": True, "data": payload} if path == "/v1/tap" else None)
    data = android_bridge.tap(12.5, 99.0)
    assert data["ok"] is True
    assert data["data"] == {"x": 12.5, "y": 99.0}

def test_click_and_verify(monkeypatch):
    monkeypatch.setattr(android_bridge, "click", lambda text: {"ok": True, "data": {"query": text}})
    monkeypatch.setattr(android_bridge, "current_ui", lambda max_depth=8: {"ok": True, "data": {"text": "Result 15"}})
    data = android_bridge.click_and_verify("=", "15", 300)
    assert data["ok"] is True
    assert data["verified"] is True


def test_click_retry_recovers(monkeypatch):
    calls = iter([{"ok": False, "error": "transient"}, {"ok": True}])
    monkeypatch.setattr(android_bridge, "click", lambda text: next(calls))
    data = android_bridge.click_retry("AC", attempts=2, delay_ms=0)
    assert data["ok"] is True
    assert data["attempts"] == 2


def test_rejects_header_unsafe_token():
    assert android_bridge._valid_accessibility_token("abc\ndef") is None
    assert android_bridge._valid_accessibility_token("abc def") is None
    assert android_bridge._valid_accessibility_token("abc_DEF-123") == "abc_DEF-123"

def test_open_app_resolves_exact_label_after_direct_miss(monkeypatch):
    calls = []
    def fake(path, payload=None):
        calls.append((path, payload))
        if path == "/v1/open" and payload == {"query": "com.android.bbkcalculator"}:
            return {"ok": True, "data": {"label": "计算器", "package": "com.android.bbkcalculator"}}
        if path == "/v1/open":
            return {"ok": False, "error": "launcher app not found"}
        if path == "/v1/apps":
            return {"ok": True, "data": [{"label": "计算器", "package": "com.android.bbkcalculator"}]}
        return None
    monkeypatch.setattr(android_bridge, "_accessibility", fake)
    data = android_bridge.open_app("计算器")
    assert data["opened"] is True
    assert data["package"] == "com.android.bbkcalculator"
    assert data["resolved_from_label"] == "计算器"

def test_wait_for_text_times_out_cleanly(monkeypatch):
    monkeypatch.setattr(android_bridge, "current_ui", lambda max_depth=8: {"ok": True, "data": {"text": "nope"}})
    data = android_bridge.wait_for_text("target", timeout_ms=100)
    assert data["ok"] is False
    assert data["verified"] is False
