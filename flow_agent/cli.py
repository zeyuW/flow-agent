from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from flow_agent.config.settings import settings
from flow_agent.marketplace.index import MarketplaceIndex
from flow_agent.marketplace.installer import MarketplaceInstaller
from flow_agent.ops.audit import AuditLogger
from flow_agent.ops.metrics import MetricsStore
from flow_agent.plugins.manager import PluginManager
from flow_agent.security.policy import SecurityPolicy
from flow_agent.runtime.workspace import (
    apply_workspace_env,
    init_workspace,
    require_workspace,
)
from flow_agent.skills.manager import SkillManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flow-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    
    init_cmd = sub.add_parser("init", help="initialize workspace")
    init_cmd.add_argument("--workspace", default=".", help="workspace directory")
    
    sub.add_parser("run", help="run agent")

    sub.add_parser("dashboard", help="start dashboard server")
    
    runtime_cmd = sub.add_parser("runtime", help="runtime controls")
    runtime_sub = runtime_cmd.add_subparsers(dest="runtime_action", required=True)
    for action in ("snapshot", "health", "reload", "restart", "stop", "start"):
        runtime_sub.add_parser(action)

    jobs_cmd = sub.add_parser("jobs", help="jobs commands")
    jobs_sub = jobs_cmd.add_subparsers(dest="jobs_action", required=True)
    jobs_sub.add_parser("list")

    channels_cmd = sub.add_parser("channels", help="channels commands")
    channels_sub = channels_cmd.add_subparsers(dest="channels_action", required=True)
    channels_sub.add_parser("list")

    sources_cmd = sub.add_parser("sources", help="sources commands")
    sources_sub = sources_cmd.add_subparsers(dest="sources_action", required=True)
    sources_sub.add_parser("list")

    skills_cmd = sub.add_parser("skills", help="skills management")
    skills_sub = skills_cmd.add_subparsers(dest="skills_action", required=True)
    skills_sub.add_parser("list")
    skill_install = skills_sub.add_parser("install")
    skill_install.add_argument("path")
    skill_enable = skills_sub.add_parser("enable")
    skill_enable.add_argument("name")
    skill_disable = skills_sub.add_parser("disable")
    skill_disable.add_argument("name")

    plugins_cmd = sub.add_parser("plugins", help="plugins management")
    plugins_sub = plugins_cmd.add_subparsers(dest="plugins_action", required=True)
    plugins_sub.add_parser("list")
    plugin_install = plugins_sub.add_parser("install")
    plugin_install.add_argument("path")
    plugin_uninstall = plugins_sub.add_parser("uninstall")
    plugin_uninstall.add_argument("name")
    plugin_enable = plugins_sub.add_parser("enable")
    plugin_enable.add_argument("name")
    plugin_disable = plugins_sub.add_parser("disable")
    plugin_disable.add_argument("name")

    market_cmd = sub.add_parser("marketplace", help="marketplace index management")
    market_sub = market_cmd.add_subparsers(dest="market_action", required=True)
    market_sub.add_parser("list")
    market_sub.add_parser("rebuild")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        layout = init_workspace(Path(args.workspace))
        print(f"workspace initialized: {layout.root}")
        return 0

    layout = require_workspace()
    apply_workspace_env(layout)
    audit = AuditLogger(layout.logs_dir / "audit.jsonl")
    metrics = MetricsStore()
    security = SecurityPolicy()
    actor = "local-user"
    role = "admin"

    if args.command == "run":
        from flow_agent.main import main as interactive_main

        cfg = settings.get()
        audit.record(
            "run",
            actor,
            {
                "config_file": ".env/default",
                "http_enabled": cfg.channels.http_enabled,
                "dashboard_enabled": cfg.channels.dashboard_enabled,
                "jobs_queue": cfg.jobs.max_async_queue,
                "subagent_max": cfg.subagent.max_concurrency,
            },
        )
        return interactive_main()

    if args.command == "dashboard":
        from flow_agent.dashboard.server import serve_dashboard

        cfg = settings.get()
        audit.record(
            "dashboard",
            actor,
            {
                "host": cfg.channels.dashboard_host,
                "port": cfg.channels.dashboard_port,
            },
        )
        serve_dashboard(
            host=cfg.channels.dashboard_host,
            port=cfg.channels.dashboard_port,
        )
        return 0

    if args.command == "runtime":
        from flow_agent.runtime.snapshot import RuntimeSnapshot

        cfg = settings.get()
        snapshot = RuntimeSnapshot(cfg)
        if args.runtime_action == "snapshot":
            data = snapshot.capture()
            print(json.dumps(data, indent=2))
        elif args.runtime_action == "health":
            health = snapshot.health_check()
            print(json.dumps(health, indent=2))
        elif args.runtime_action == "reload":
            settings.reload()
            print("settings reloaded")
        elif args.runtime_action == "restart":
            print("restart not implemented")
        elif args.runtime_action == "stop":
            print("stop not implemented")
        elif args.runtime_action == "start":
            print("start not implemented")
        return 0

    if args.command == "jobs":
        if args.jobs_action == "list":
            from flow_agent.background.queue import JobQueue

            queue = JobQueue()
            jobs = queue.list_jobs()
            print(json.dumps(jobs, indent=2))
        return 0

    if args.command == "channels":
        if args.channels_action == "list":
            cfg = settings.get()
            channels = {
                "cli": cfg.channels.cli_enabled,
                "http": cfg.channels.http_enabled,
                "dashboard": cfg.channels.dashboard_enabled,
                "qq": cfg.channels.qq_enabled,
            }
            print(json.dumps(channels, indent=2))
        return 0

    if args.command == "sources":
        if args.sources_action == "list":
            from flow_agent.proactive.sources import list_sources

            sources = list_sources()
            print(json.dumps(sources, indent=2))
        return 0

    if args.command == "skills":
        manager = SkillManager()
        if args.skills_action == "list":
            skills = manager.list_skills()
            print(json.dumps(skills, indent=2))
        elif args.skills_action == "install":
            manager.install_skill(args.path)
            print(f"skill installed: {args.path}")
        elif args.skills_action == "enable":
            manager.enable_skill(args.name)
            print(f"skill enabled: {args.name}")
        elif args.skills_action == "disable":
            manager.disable_skill(args.name)
            print(f"skill disabled: {args.name}")
        return 0

    if args.command == "plugins":
        manager = PluginManager()
        if args.plugins_action == "list":
            plugins = manager.list_plugins()
            print(json.dumps(plugins, indent=2))
        elif args.plugins_action == "install":
            manager.install_plugin(args.path)
            print(f"plugin installed: {args.path}")
        elif args.plugins_action == "uninstall":
            manager.uninstall_plugin(args.name)
            print(f"plugin uninstalled: {args.name}")
        elif args.plugins_action == "enable":
            manager.enable_plugin(args.name)
            print(f"plugin enabled: {args.name}")
        elif args.plugins_action == "disable":
            manager.disable_plugin(args.name)
            print(f"plugin disabled: {args.name}")
        return 0

    if args.command == "marketplace":
        index = MarketplaceIndex()
        if args.market_action == "list":
            items = index.list_items()
            print(json.dumps(items, indent=2))
        elif args.market_action == "rebuild":
            index.rebuild()
            print("marketplace index rebuilt")
        return 0

    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
