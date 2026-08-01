from pathlib import Path


def test_verify_script_uses_pytest_collection_by_default():
    repository_root = Path(__file__).parents[2]
    script = (repository_root / "scripts" / "verify.sh").read_text(encoding="utf-8")
    backend_script = (repository_root / "scripts" / "verify-backend.sh").read_text(
        encoding="utf-8"
    )
    workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "verify-backend.sh" in script
    assert "compileall -q backend/src" in backend_script
    assert "-m pytest -q backend/tests" in backend_script
    assert "-m pyright" in backend_script
    assert "-m black" in backend_script
    assert "git diff --check" in backend_script
    assert "black pyright" in workflow
    assert "TEST_ARGS=(" not in script
