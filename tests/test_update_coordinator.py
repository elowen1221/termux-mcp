import subprocess
from pathlib import Path
from termux_mcp.install_guard import MARKER,mark_managed_install
from termux_mcp.known_good import make_known_good,read_known_good
from termux_mcp.update_manifest import make_manifest
from termux_mcp.update_coordinator import run_update

def git(p,*a): return subprocess.check_output(['git',*a],cwd=p,text=True).strip()
def setup(tmp_path):
 p=tmp_path/'repo'; p.mkdir(); subprocess.check_call(['git','init','-q',p]); git(p,'config','user.email','x@y.invalid'); git(p,'config','user.name','x'); (p/'app').write_text('GOOD\n'); git(p,'add','.'); git(p,'commit','-qm','good'); rev=git(p,'rev-parse','HEAD'); (p/'.git/info/exclude').write_text(MARKER+'\n'); mark_managed_install(p,'0.10.2',rev); cfg=tmp_path/'config.env'; cfg.write_text('GOOD_CONFIG=1\n'); return p,cfg,rev

def test_bad_candidate_restores_app_and_config(tmp_path):
 p,cfg,rev=setup(tmp_path); kg=make_known_good('0.10.2',rev,1)
 def install():
  (p/'app').write_text('BROKEN\n'); git(p,'add','app'); git(p,'commit','-qm','candidate'); mark_managed_install(p,'0.10.3',git(p,'rev-parse','HEAD')); cfg.write_text('NEW_CONFIG=1\n')
 r=run_update(repo=p,manifest=make_manifest('0.10.2','0.10.3'),mutable_paths=[cfg],known_good=kg,install=install,migrate=lambda:None,validate=lambda:(_ for _ in ()).throw(RuntimeError('doctor failed')),app_bundle=tmp_path/'app.bundle',config_snapshot_dir=tmp_path/'cfgsnap',known_good_path=tmp_path/'kg.json')
 assert not r['ok'] and r['rolled_back'] and r['stage']=='validate'; assert (p/'app').read_text()=='GOOD\n'; assert cfg.read_text()=='GOOD_CONFIG=1\n'; assert git(p,'rev-parse','HEAD')==rev

def test_good_candidate_is_promoted(tmp_path):
 p,cfg,rev=setup(tmp_path); kg=make_known_good('0.10.2',rev,1)
 def install():
  (p/'app').write_text('NEW\n'); git(p,'add','app'); git(p,'commit','-qm','candidate'); mark_managed_install(p,'0.10.3',git(p,'rev-parse','HEAD'))
 r=run_update(repo=p,manifest=make_manifest('0.10.2','0.10.3'),mutable_paths=[cfg],known_good=kg,install=install,migrate=lambda:None,validate=lambda:None,app_bundle=tmp_path/'app.bundle',config_snapshot_dir=tmp_path/'cfgsnap',known_good_path=tmp_path/'kg.json')
 assert r['ok']; saved=read_known_good(tmp_path/'kg.json'); assert saved.version=='0.10.3'; assert saved.revision==git(p,'rev-parse','HEAD'); assert (p/'app').read_text()=='NEW\n'

def test_developer_checkout_is_refused_before_install(tmp_path):
 p,cfg,rev=setup(tmp_path); (p/MARKER).unlink(); called=[]
 r=run_update(repo=p,manifest=make_manifest('0.10.2','0.10.3'),mutable_paths=[cfg],known_good=make_known_good('0.10.2',rev,1),install=lambda:called.append(1),migrate=lambda:None,validate=lambda:None,app_bundle=tmp_path/'a.bundle',config_snapshot_dir=tmp_path/'s',known_good_path=tmp_path/'k')
 assert not r['ok'] and r['stage']=='preflight' and called==[]
