import subprocess
from pathlib import Path
from termux_mcp.known_good import make_known_good,write_known_good,read_known_good,snapshot_application,restore_application

def git(cwd,*args): return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()
def init_repo(p):
    subprocess.check_call(['git','init','-q',p]); git(p,'config','user.email','test@example.invalid'); git(p,'config','user.name','Test')

def test_known_good_roundtrip(tmp_path):
    p=tmp_path/'kg.json'; x=make_known_good('1.2.3','abc',2); write_known_good(x,p); y=read_known_good(p); assert (y.version,y.revision,y.config_schema)==('1.2.3','abc',2)

def test_application_bundle_can_restore_bad_candidate(tmp_path):
    repo=tmp_path/'repo'; repo.mkdir(); init_repo(repo); f=repo/'app.txt'; f.write_text('GOOD\n'); git(repo,'add','.'); git(repo,'commit','-qm','good'); good=git(repo,'rev-parse','HEAD')
    bundle=snapshot_application(repo,tmp_path/'snapshot.bundle')
    f.write_text('BROKEN\n'); git(repo,'commit','-qam','bad candidate'); assert f.read_text()=='BROKEN\n'
    restore_application(repo,bundle,good); assert git(repo,'rev-parse','HEAD')==good; assert f.read_text()=='GOOD\n'
