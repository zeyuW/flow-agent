import json
from pathlib import Path

from flow_agent.cli import main as cli_main
from flow_agent.plugins.manager import PluginManager
from flow_agent.runtime.workspace import detect_workspace, init_workspace, persist_workspace_profile
from flow_agent.skills.manager import SkillManager


def test_workspace_init_and_detect(tmp_path: Path):
    layout = init_workspace(tmp_path)
    assert layout.marker_file.exists()
    detected = detect_workspace(tmp_path / "skills")
    assert detected is not None
    assert detected.root == tmp_path.resolve()


def test_skill_manager_install_enable_disable(tmp_path: Path):
    layout = init_workspace(tmp_path)
    source = tmp_path / "src_skill"
    source.mkdir()
    (source / "skill.json").write_text(
        json.dumps(
            {
                "name": "weather",
                "description": "weather skill",
                "version": "1.0.0",
                "compatibility": ">=1.0.0",
                "metadata": {"author": "tester"},
            }
        ),
        encoding="utf-8",
    )
    manager = SkillManager(layout.skills_dir)
    manifest = manager.install(source)
    assert manifest.name == "weather"
    manager.disable("weather")
    assert manager.scan()[0].enabled is False
    manager.enable("weather")
    assert manager.scan()[0].enabled is True


def test_plugin_manager_install_enable_disable_uninstall(tmp_path: Path):
    layout = init_workspace(tmp_path)
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


def test_cli_init_command(tmp_path: Path):
    exit_code = cli_main(["init", "--workspace", str(tmp_path)])
    assert exit_code == 0
    assert (tmp_path / ".flow" / ".workspace").exists()


def test_persist_workspace_profile_updates_config(tmp_path: Path):
    layout = init_workspace(tmp_path)
    persist_workspace_profile(layout, "prod")
    text = layout.config_file.read_text(encoding="utf-8")
    assert "[governance]" in text
    assert 'profile = "prod"' in text
