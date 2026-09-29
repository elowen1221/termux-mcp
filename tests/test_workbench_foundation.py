from pathlib import Path
import subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
WB = ROOT / "workbench_foundation"


def run(*args):
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, text=True, capture_output=True)


def test_manifest_and_required_public_files_exist():
    for name in ("MANIFEST.toml", "RULES.md", "USER.example.md", "HANDOFF.example.md", "BOX_README.template.md"):
        assert (WB / name).is_file()


def test_public_contract_templates_are_parseable():
    import tomllib
    manifest = tomllib.loads((WB / "MANIFEST.toml").read_text())
    assert list(manifest["notes"]) == ["rules", "user", "handoff"]
    assert set(manifest["categories"]) == {"boxes", "scratch", "archive"}


def test_packaged_workbench_api_round_trip(tmp_path):
    from termux_mcp import workbench
    ctx = workbench.context(tmp_path)
    assert set(ctx["categories"]) == {"boxes", "scratch", "archive"}
    assert workbench.doctor(tmp_path)["ok"] is True
    made = workbench.new_box("demo-box", tmp_path)
    assert made == {"created": True, "box": "demo-box"}
    ctx = workbench.context(tmp_path)
    assert ctx["boxes"][0]["name"] == "demo-box"
    assert ctx["boxes"][0]["contract_ok"] is True


def test_first_install_creates_local_notes_and_empty_categories(tmp_path):
    from termux_mcp import workbench
    root = workbench.ensure(tmp_path)
    assert (root / "USER.md").is_file()
    assert (root / "HANDOFF.md").is_file()
    for rel in ("boxes", "scratch", "archive"):
        assert (root / rel).is_dir()


def test_doctor_reports_box_missing_readme(tmp_path):
    from termux_mcp import workbench
    root = workbench.ensure(tmp_path)
    (root / "boxes" / "broken-box").mkdir()
    report = workbench.doctor(root)
    assert report["ok"] is False
    assert {"kind": "missing-box-entry", "target": "broken-box"} in report["issues"]


def test_user_and_handoff_content_are_local_instance_state(tmp_path):
    from termux_mcp import workbench
    root = workbench.ensure(tmp_path)
    (root / "USER.md").write_text("# User\nnever auto-push\n")
    (root / "HANDOFF.md").write_text("# Handoff\ncontinue demo-box\n")
    ctx = workbench.context(root)
    assert "never auto-push" in ctx["notes"]["user"]
    assert "continue demo-box" in ctx["notes"]["handoff"]
    assert not (Path(__file__).resolve().parents[1] / "workbench_foundation" / "USER.md").exists()
