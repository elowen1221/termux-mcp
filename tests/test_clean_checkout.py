"""Clean-checkout regression test.

Guards against the class of bug where a module exists in the working tree
but is NOT tracked by git (e.g. accidentally matched by a .gitignore
pattern), so a fresh clone / install from the committed tree breaks at
import time (e.g. `ImportError: cannot import name 'tunnel'`).

The test exports the staged tree (`git write-tree`) into a temp dir, then
runs the CLI from that tree and asserts the key commands start without an
ImportError / traceback.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Modules the CLI imports at startup — must exist in the committed tree.
REQUIRED_FILES = [
    "termux_mcp/__init__.py",
    "termux_mcp/__main__.py",
    "termux_mcp/auth.py",
    "termux_mcp/cli.py",
    "termux_mcp/config.py",
    "termux_mcp/handler.py",
    "termux_mcp/mcp_server.py",
    "termux_mcp/managed_mcp.py",
    "termux_mcp/onboarding.py",
    "termux_mcp/oauth.py",
    "termux_mcp/operations.py",
    "termux_mcp/permissions.py",
    "termux_mcp/process.py",
    "termux_mcp/server.py",
    "termux_mcp/tunnel.py",
    "scripts/install.sh",
    "docs/oauth.md",
    "pyproject.toml",
]


def _export_staged_tree(tmp: str) -> None:
    """Export the staged tree (git write-tree) into tmp."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    tree = subprocess.run(
        ["git", "write-tree"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    tar_path = os.path.join(tmp, "tree.tar")
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", tar_path, tree],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    with tarfile.open(tar_path) as tf:
        tf.extractall(tmp)


def test_staged_tree_contains_all_required_files():
    with tempfile.TemporaryDirectory() as tmp:
        _export_staged_tree(tmp)
        missing = [f for f in REQUIRED_FILES if not os.path.exists(os.path.join(tmp, f))]
        assert not missing, f"files missing from staged tree: {missing}"


def test_cli_starts_from_clean_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        _export_staged_tree(tmp)
        env = os.environ.copy()
        env["PYTHONPATH"] = tmp
        env["HOME"] = tmp  # isolate config/state

        # --help must exit 0.
        r = subprocess.run(
            [sys.executable, "-m", "termux_mcp", "--help"],
            cwd=tmp, env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"--help failed:\n{r.stderr}"

        # doctor / status must run to completion without a traceback.
        # (They may exit non-zero by design when the server is not running.)
        for cmd in (["-m", "termux_mcp", "doctor"], ["-m", "termux_mcp", "status"]):
            r = subprocess.run(
                [sys.executable] + cmd,
                cwd=tmp, env=env, capture_output=True, text=True, timeout=60,
            )
            assert "Traceback" not in r.stderr, f"{cmd} crashed:\n{r.stderr}"
            assert "ImportError" not in r.stderr, f"{cmd} crashed:\n{r.stderr}"
            assert r.stdout.strip(), f"{cmd} produced no output"
