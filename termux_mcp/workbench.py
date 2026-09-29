"""AI-facing workspace organization for long-lived Termux-MCP installations."""
from __future__ import annotations

from pathlib import Path
import os, re, shutil, tomllib

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = PACKAGE_ROOT / "workbench_foundation"
DEFAULT_ROOT = Path(os.environ.get("TERMUX_MCP_WORKBENCH", Path.home() / ".termux-mcp" / "workbench"))


def _root(root: str | Path | None = None) -> Path:
    return Path(root).expanduser() if root else DEFAULT_ROOT


def _manifest(root: Path) -> dict:
    return tomllib.loads((root / "MANIFEST.toml").read_text())


def ensure(root: str | Path | None = None) -> Path:
    root = _root(root)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("MANIFEST.toml", "RULES.md", "BOX_README.template.md"):
        dst = root / name
        if not dst.exists(): shutil.copyfile(TEMPLATE_ROOT / name, dst)
    for name in ("USER.md", "HANDOFF.md"):
        p = root / name
        if not p.exists(): p.write_text("# " + name.removesuffix(".md").title() + "\n")
    m = _manifest(root)
    for rel in m["categories"].values(): (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def context(root: str | Path | None = None) -> dict:
    root = ensure(root); m = _manifest(root)
    notes = {key: (root / rel).read_text().strip() for key, rel in m["notes"].items()}
    boxes_dir = root / m["categories"]["boxes"]; entry = m["contracts"]["box"]["entry"]
    boxes = []
    for box in sorted(p for p in boxes_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        readme = box / entry
        summary = ""
        if readme.exists():
            summary = next((x.strip() for x in readme.read_text(errors="replace").splitlines() if x.strip() and not x.lstrip().startswith("#")), "")
        boxes.append({"name": box.name, "summary": summary, "contract_ok": readme.is_file()})
    return {"notes": notes, "categories": m["categories"], "boxes": boxes}


def doctor(root: str | Path | None = None) -> dict:
    root = ensure(root); m = _manifest(root); issues = []
    for name, rel in m["categories"].items():
        if not (root / rel).is_dir(): issues.append({"kind": "missing-category", "target": name})
    boxes_dir = root / m["categories"]["boxes"]; entry = m["contracts"]["box"]["entry"]
    for box in sorted(p for p in boxes_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if not (box / entry).is_file(): issues.append({"kind": "missing-box-entry", "target": box.name})
    return {"ok": not issues, "issues": issues}


def new_box(name: str, root: str | Path | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name): return {"created": False, "error": "invalid box name"}
    root = ensure(root); m = _manifest(root); box = root / m["categories"]["boxes"] / name
    if box.exists(): return {"created": False, "error": "box already exists", "box": name}
    box.mkdir(); template = (root / "BOX_README.template.md").read_text().replace("<box name>", name)
    (box / m["contracts"]["box"]["entry"]).write_text(template)
    (box / m["contracts"]["box"]["history"]).write_text(f"# {name} log\n")
    return {"created": True, "box": name}
