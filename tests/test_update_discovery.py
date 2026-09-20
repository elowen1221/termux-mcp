from termux_mcp import update_discovery as u

def test_product_tags_ignore_non_version(monkeypatch):
 monkeypatch.setattr(u.subprocess,'check_output',lambda *a,**k:'a refs/tags/android-companion-latest\nb refs/tags/v0.8.4\nc refs/tags/v0.10.3\n')
 assert u.origin_release_tags()==['v0.8.4','v0.10.3']

def test_update_available(monkeypatch):
 monkeypatch.setattr(u,'origin_release_tags',lambda *a,**k:['v0.10.2','v0.10.3'])
 r=u.check_updates('0.10.2'); assert r.update_available and r.status=='update_available' and r.latest_tag=='v0.10.3'

def test_up_to_date(monkeypatch):
 monkeypatch.setattr(u,'origin_release_tags',lambda *a,**k:['v0.10.2'])
 r=u.check_updates('0.10.2'); assert not r.update_available and r.status=='up_to_date'

def test_installed_ahead_never_proposes_downgrade(monkeypatch):
 monkeypatch.setattr(u,'origin_release_tags',lambda *a,**k:['v0.8.4'])
 r=u.check_updates('0.10.2'); assert not r.update_available and r.status=='installed_ahead_of_release_baseline'

def test_release_discovery_does_not_require_git_checkout(monkeypatch):
 calls=[]
 def fake(cmd,**kwargs): calls.append((cmd,kwargs)); return 'a refs/tags/v0.10.2\n'
 monkeypatch.setattr(u.subprocess,'check_output',fake); u.origin_release_tags()
 assert 'cwd' not in calls[0][1] and calls[0][0][-1]==u.DEFAULT_RELEASE_REMOTE
