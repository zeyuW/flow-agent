import json
from pathlib import Path

from flow_agent.cli import main as cli_main
from flow_agent.marketplace.index import MarketplaceIndex
from flow_agent.marketplace.installer import MarketplaceInstaller
from flow_agent.plugins.manager import PluginManager
from flow_agent.runtime.workspace import init_workspace
from flow_agent.security.policy import SecurityPolicy
from flow_agent.skills.manager import SkillManager


def test_security_policy_blocks_user_runtime_start():
    policy = SecurityPolicy()
    allowed, reason = policy.check_command(role="user", action="runtime.start")
    assert allowed is False
    assert "forbidden" in reason


def test_marketplace_rebuild_collects_skill_plugin(tmp_path: Path):
    layout = init_workspace(tmp_path)
    skill_src = tmp_path / "src_skill"
    skill_src.mkdir()
    (skill_src / "skill.json").write_text(
        json.dumps(
            {
                "name": "weather",
                "description": "weather skill",
                "version": "1.0.0",
                "compatibility": ">=1.0.0",
            }
        ),
        encoding="utf-8",
    )
    plugin_src = tmp_path / "src_plugin"
    plugin_src.mkdir()
    (plugin_src / "plugin.json").write_text(
        json.dumps(
            {
                "name": "pdf_parser",
                "description": "plugin",
                "version": "1.0.0",
                "compatibility": ">=1.0.0",
            }
        ),
        encoding="utf-8",
    )
    skills = SkillManager(layout.skills_dir)
    plugins = PluginManager(layout.plugins_dir)
    skills.install(skill_src)
    plugins.install(plugin_src)
    installer = MarketplaceInstaller(
        index=MarketplaceIndex(layout.data_dir / "marketplace-index.json"),
        skills=skills,
        plugins=plugins,
    )
    rows = installer.rebuild_local_index()
    names = {row.name for row in rows}
    assert names == {"weather", "pdf_parser"}
    assert (layout.data_dir / "marketplace-index.json").exists()


def test_cli_runtime_start_denied_for_user_role(tmp_path: Path, monkeypatch):
    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLOW_AGENT_ACTOR_ROLE", "user")
    try:
        cli_main(["runtime", "start"])
    except PermissionError as exc:
        assert "forbidden" in str(exc)
    else:
        raise AssertionError("expected PermissionError for user runtime start")
