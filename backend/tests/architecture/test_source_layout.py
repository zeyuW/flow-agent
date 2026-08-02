from importlib.util import find_spec
from pathlib import Path

REPOSITORY_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / ".git").exists()
)
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
SOURCE_ROOT = BACKEND_ROOT / "src"


def test_python_packages_resolve_from_backend_src():
    for package_name in ("modules", "interfaces", "infra", "bootstrap"):
        spec = find_spec(package_name)
        assert spec is not None
        locations = list(spec.submodule_search_locations or ())
        assert locations
        assert Path(locations[0]).resolve().is_relative_to(SOURCE_ROOT.resolve())


def test_legacy_python_package_is_not_present():
    assert not (SOURCE_ROOT / "flow_agent").exists()


def test_runtime_workspace_stays_at_repository_root():
    from infra.paths import PROJECT_ROOT

    assert PROJECT_ROOT == REPOSITORY_ROOT
