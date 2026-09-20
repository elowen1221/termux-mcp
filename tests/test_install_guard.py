import subprocess
from termux_mcp.install_guard import mark_managed_install,assess_install,MARKER

def git(p,*a): return subprocess.check_output(['git',*a],cwd=p,text=True).strip()
def repo(tmp_path):
 p=tmp_path/'r'; p.mkdir(); subprocess.check_call(['git','init','-q',p]); git(p,'config','user.email','x@y.invalid'); git(p,'config','user.name','x'); (p/'app').write_text('ok'); git(p,'add','.'); git(p,'commit','-qm','init'); return p

def test_unmarked_checkout_is_not_rollback_safe(tmp_path):
 p=repo(tmp_path); a=assess_install(p); assert not a.managed and not a.rollback_safe

def test_managed_clean_checkout_is_safe(tmp_path):
 p=repo(tmp_path); rev=git(p,'rev-parse','HEAD'); (p/'.git/info/exclude').write_text(MARKER+'\n'); mark_managed_install(p,'1.0',rev); a=assess_install(p); assert a.rollback_safe

def test_dirty_checkout_is_refused(tmp_path):
 p=repo(tmp_path); rev=git(p,'rev-parse','HEAD'); (p/'.git/info/exclude').write_text(MARKER+'\n'); mark_managed_install(p,'1.0',rev); (p/'app').write_text('mine'); a=assess_install(p); assert not a.rollback_safe and any('user/uncommitted' in x for x in a.reasons)

def test_revision_drift_is_refused(tmp_path):
 p=repo(tmp_path); rev=git(p,'rev-parse','HEAD'); (p/'.git/info/exclude').write_text(MARKER+'\n'); mark_managed_install(p,'1.0',rev); (p/'other').write_text('x'); git(p,'add','other'); git(p,'commit','-qm','other'); a=assess_install(p); assert not a.rollback_safe and any('HEAD differs' in x for x in a.reasons)
