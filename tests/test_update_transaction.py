from pathlib import Path
from termux_mcp.update_transaction import create_snapshot,restore_snapshot,run_transaction

def test_snapshot_restore_file(tmp_path):
    f=tmp_path/'config.env'; f.write_text('OLD=1\n'); s=create_snapshot([f],tmp_path/'snap'); f.write_text('NEW=1\n'); restore_snapshot(s); assert f.read_text()=='OLD=1\n'

def test_failed_validation_rolls_back(tmp_path):
    f=tmp_path/'config.env'; f.write_text('OLD=1\n')
    def install(): f.write_text('INSTALLED=1\n')
    def migrate(): f.write_text('MIGRATED=1\n')
    def validate(): raise RuntimeError('doctor failed')
    r=run_transaction(mutable_paths=[f],install=install,migrate=migrate,validate=validate,snapshot_dir=tmp_path/'snap')
    assert r['ok'] is False and r['failed_stage']=='validate' and r['rolled_back'] is True
    assert f.read_text()=='OLD=1\n'

def test_success_keeps_new_state(tmp_path):
    f=tmp_path/'config.env'; f.write_text('OLD=1\n')
    r=run_transaction(mutable_paths=[f],install=lambda:f.write_text('NEW=1\n'),migrate=lambda:None,validate=lambda:None,snapshot_dir=tmp_path/'snap')
    assert r['ok'] is True and r['rolled_back'] is False and f.read_text()=='NEW=1\n'

def test_restore_removes_file_created_after_snapshot(tmp_path):
    f=tmp_path/'new.env'; s=create_snapshot([f],tmp_path/'snap'); f.write_text('created'); restore_snapshot(s); assert not f.exists()
