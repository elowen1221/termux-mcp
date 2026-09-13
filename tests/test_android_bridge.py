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
