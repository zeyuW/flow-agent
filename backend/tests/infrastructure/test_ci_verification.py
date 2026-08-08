from pathlib import Path


def test_ci_runs_backend_verification_without_deleted_scripts():
    repository_root = Path(__file__).parents[3]
    workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m compileall -q backend/src" in workflow
    assert "python -m pytest -q backend/tests" in workflow
    assert "python -m pyright" in workflow
    assert "python -m black" in workflow
    assert "git diff --check" in workflow
    assert "scripts/" not in workflow
