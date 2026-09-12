from pathlib import Path

import pytest

from termux_mcp.domain_migration import RewriteTarget, apply_url_rewrites, plan_url_rewrites


def test_plan_reports_counts_without_exposing_contents(tmp_path):
    project = tmp_path / "Termux-MCP"
    home = tmp_path / "home"
    public = project / "stack.sh"
    secret = home / ".config" / "termux-mcp" / "config.env"
    public.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    public.write_text("https://termux.old.example/mcp\nhttps://weather.old.example/mcp\n", encoding="utf-8")
    secret.write_text("TOKEN=super-secret\nURL=https://alpaca.old.example/mcp\n", encoding="utf-8")
    targets = [RewriteTarget(public, required=True), RewriteTarget(secret)]

    plans = plan_url_rewrites(
        "old.example", "new.example", targets=targets, project_root=project, home=home
    )
    assert [(p.path, p.replacements, p.secret) for p in plans] == [
        (public, 2, False),
        (secret, 1, True),
    ]
    assert "super-secret" not in repr(plans)


def test_apply_preserves_subdomains_and_creates_backups(tmp_path):
    project = tmp_path / "Termux-MCP"
    home = tmp_path / "home"
    target = project / "stack.sh"
    target.parent.mkdir(parents=True)
    original = "https://termux.walnutnest.buzz/mcp\nhttps://alpaca.walnutnest.buzz/mcp\n"
    target.write_text(original, encoding="utf-8")

    results = apply_url_rewrites(
        "walnutnest.buzz",
        "cheap-next.xyz",
        targets=[RewriteTarget(target, required=True)],
        project_root=project,
        home=home,
    )
    assert target.read_text(encoding="utf-8") == (
        "https://termux.cheap-next.xyz/mcp\nhttps://alpaca.cheap-next.xyz/mcp\n"
    )
    assert len(results) == 1
    assert Path(results[0][1]).read_text(encoding="utf-8") == original


def test_does_not_rewrite_domain_embedded_in_larger_hostname(tmp_path):
    target = tmp_path / "config.txt"
    target.write_text("https://notwalnutnest.buzz/x\nhttps://walnutnest.buzz/x\n", encoding="utf-8")
    apply_url_rewrites(
        "walnutnest.buzz",
        "next.example",
        targets=[RewriteTarget(target)],
        project_root=tmp_path,
        home=tmp_path,
    )
    assert target.read_text(encoding="utf-8") == (
        "https://notwalnutnest.buzz/x\nhttps://next.example/x\n"
    )


def test_required_missing_target_fails_before_apply(tmp_path):
    missing = tmp_path / "missing.env"
    with pytest.raises(FileNotFoundError, match="required migration target"):
        plan_url_rewrites(
            "old.example",
            "new.example",
            targets=[RewriteTarget(missing, required=True)],
            project_root=tmp_path,
            home=tmp_path,
        )


def test_apply_preserves_private_file_mode(tmp_path):
    home = tmp_path / "home"
    secret = home / ".config" / "termux-mcp" / "config.env"
    secret.parent.mkdir(parents=True)
    secret.write_text("URL=https://termux.old.example\n", encoding="utf-8")
    secret.chmod(0o600)
    apply_url_rewrites(
        "old.example",
        "new.example",
        targets=[RewriteTarget(secret)],
        project_root=tmp_path,
        home=home,
    )
    assert secret.stat().st_mode & 0o777 == 0o600


def test_invalid_domain_is_rejected(tmp_path):
    target = tmp_path / "config.txt"
    target.write_text("https://termux.old.example\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid domain"):
        plan_url_rewrites(
            "old.example",
            "bad/domain",
            targets=[RewriteTarget(target)],
            project_root=tmp_path,
            home=tmp_path,
        )
