"""Coordinates a guarded transactional application + configuration update."""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Iterable
from .install_guard import assess_install
from .known_good import KnownGood, snapshot_application, restore_application, write_known_good
from .update_transaction import create_snapshot, restore_snapshot
from .update_manifest import UpdateManifest


def run_update(*, repo:Path, manifest:UpdateManifest, mutable_paths:Iterable[Path], known_good:KnownGood, install:Callable[[],None], migrate:Callable[[],None], validate:Callable[[],None], app_bundle:Path, config_snapshot_dir:Path, known_good_path:Path):
    errors=manifest.validate()
    if errors: return {'ok':False,'stage':'preflight','rolled_back':False,'errors':errors}
    guard=assess_install(repo)
    if not guard.rollback_safe:
        return {'ok':False,'stage':'preflight','rolled_back':False,'errors':list(guard.reasons)}
    if guard.revision != known_good.revision:
        return {'ok':False,'stage':'preflight','rolled_back':False,'errors':['current revision does not equal known-good revision']}
    snapshot_application(repo,app_bundle)
    cfg=create_snapshot(mutable_paths,config_snapshot_dir)
    stage='install'
    try:
        install(); stage='migrate'; migrate(); stage='validate'; validate()
    except Exception as exc:
        restore_snapshot(cfg)
        restore_application(repo,app_bundle,known_good.revision)
        return {'ok':False,'stage':stage,'rolled_back':True,'error':str(exc)}
    # The candidate installer is responsible for updating its managed marker.
    # Only after validation do we promote it to known-good.
    new_guard=assess_install(repo)
    if not new_guard.managed or new_guard.revision is None:
        restore_snapshot(cfg); restore_application(repo,app_bundle,known_good.revision)
        return {'ok':False,'stage':'commit','rolled_back':True,'error':'candidate did not produce a managed install'}
    promoted=KnownGood(manifest.to_version,new_guard.revision,manifest.to_config_schema,known_good.recorded_at)
    write_known_good(promoted,known_good_path)
    return {'ok':True,'stage':'commit','rolled_back':False,'revision':new_guard.revision}
