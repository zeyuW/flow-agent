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


def test_ci_and_pre_commit_check_committed_changes_with_locked_environment():
    repository_root = Path(__file__).parents[3]
    workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    hook = (repository_root / ".githooks" / "pre-commit").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert "uv sync --locked" in workflow
    assert 'git diff --check "${BEFORE_SHA}" "${CURRENT_SHA}"' in workflow
    assert "backend/src/infra/config.py" in workflow
    assert "git diff --cached --check" not in hook
    assert "uv run --project backend" in hook
    assert "UV_CACHE_DIR" in hook
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in hook
