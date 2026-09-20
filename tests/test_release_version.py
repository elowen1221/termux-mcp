import importlib.util
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'scripts/check-version.py'
spec=importlib.util.spec_from_file_location('check_version',P); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def test_package_version_matches_canonical(): assert m.pyproject_version()==m.init_version()
def test_canonical_version_is_nonempty(): assert m.pyproject_version().strip()
