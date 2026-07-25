from pathlib import Path


def test_verify_script_uses_pytest_collection_by_default():
    script = (Path(__file__).parents[1] / "scripts" / "verify.sh").read_text(
        encoding="utf-8"
    )

    assert '"${PYTHON_BIN}" -m pytest -q' in script
    assert "TEST_ARGS=(" not in script
