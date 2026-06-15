from pathlib import Path

from flow_agent.ops.release_gate import run_release_gate


def test_release_gate_passes_in_repo_root():
    project_root = Path(__file__).resolve().parents[1]
    result = run_release_gate(project_root)
    assert "required_tests_present" in result.checks
    assert "config_files_present" in result.checks
    assert "stage_doc_present" in result.checks
