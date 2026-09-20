from termux_mcp.update_manifest import UpdateManifest,make_manifest

def test_default_manifest_separates_persistent_and_runtime():
    m=make_manifest('0.10.2','0.10.3')
    assert not (set(m.rollback_paths)&set(m.ephemeral_paths)); assert m.validate()==[]

def test_schema_change_requires_migration():
    m=UpdateManifest('1','2',1,2,('config',),('pid',),None)
    assert any('migration' in x for x in m.validate())

def test_overlap_is_rejected():
    m=UpdateManifest('1','2',1,1,('same',),('same',),None)
    assert any('both rollback and ephemeral' in x for x in m.validate())

def test_schema_change_with_migration_is_valid():
    m=UpdateManifest('1','2',1,2,('config',),('pid',),'migrate_1_to_2')
    assert m.validate()==[]
