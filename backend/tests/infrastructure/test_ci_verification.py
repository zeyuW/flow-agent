from pathlib import Path


def test_verify_script_uses_pytest_collection_by_default():
    repository_root = Path(__file__).parents[3]
    script = (repository_root / "scripts" / "verify-backend.sh").read_text(
        encoding="utf-8"
    )
    backend_script = (repository_root / "scripts" / "verify-backend.sh").read_text(
        encoding="utf-8"
    )
    workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "pytest -q backend/test" in script
    assert "compileall -q backend/src" in backend_script
    assert "-m pytest -q backend/test" in backend_script
    assert "-m pyright" in backend_script
    assert "-m black" in backend_script
    assert "git diff --check" in backend_script
    assert "black pyright" in workflow
    assert "TEST_ARGS=(" not in script
