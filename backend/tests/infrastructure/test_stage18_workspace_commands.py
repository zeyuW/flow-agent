import json
from pathlib import Path

from application.capabilities.plugins.manager import PluginManager
from infra.workspace import (
    detect_workspace,
    init_workspace,
    persist_workspace_profile,
)


def test_workspace_init_and_detect(tmp_path: Path):
    runtime_dir = tmp_path / "user" / ".flow"
    layout = init_workspace(tmp_path, runtime_dir=runtime_dir)
    assert layout.marker_file.exists()
    assert layout.project_skills_dir == tmp_path / "skills"
    assert layout.installed_skills_dir == runtime_dir / "skills"
    assert (layout.project_skills_dir / "README.md").is_file()
    assert layout.memory_dir.is_dir()
    assert layout.memory_journal_dir.is_dir()
    assert layout.drift_skills_dir.is_dir()
    assert layout.plugin_data_dir.is_dir()
    assert layout.mcp_dir == runtime_dir / "mcp"
    assert layout.mcp_dir.is_dir()
    assert not (runtime_dir / "sources").exists()
    assert layout.inbound_attachments_dir.is_dir()
    assert layout.outbound_attachments_dir.is_dir()
    assert layout.proactive_trace_file.exists()
    assert layout.mcp_config_file.exists()
    detected = detect_workspace(tmp_path / "skills", runtime_dir=runtime_dir)
    assert detected is not None
    assert detected.root == tmp_path.resolve()


def test_plugin_manager_install_enable_disable_uninstall(tmp_path: Path):
    layout = init_workspace(tmp_path, runtime_dir=tmp_path / "user" / ".flow")
    source = tmp_path / "src_plugin"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "name": "pdf_parser",
                "description": "parse pdf",
                "version": "1.0.0",
                "compatibility": ">=1.0.0",
                "metadata": {"author": "tester"},
            }
        ),
        encoding="utf-8",
    )
    manager = PluginManager(layout.plugins_dir)
    manifest = manager.install(source)
    assert manifest.name == "pdf_parser"
    manager.disable("pdf_parser")
    assert manager.scan()[0].enabled is False
    manager.enable("pdf_parser")
    assert manager.scan()[0].enabled is True
    manager.uninstall("pdf_parser")
    assert manager.scan() == []


def test_persist_workspace_profile_is_noop(tmp_path: Path):
    layout = init_workspace(tmp_path, runtime_dir=tmp_path / "user" / ".flow")
    marker_before = layout.marker_file.read_text(encoding="utf-8")
    persist_workspace_profile(layout, "prod")
    assert layout.marker_file.read_text(encoding="utf-8") == marker_before
