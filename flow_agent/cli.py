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
    actor = os.getenv("FLOW_AGENT_ACTOR", "local-user")
    role = os.getenv("FLOW_AGENT_ACTOR_ROLE", "admin")

    if args.command == "run":
        from flow_agent.main import main as interactive_main

        cfg = settings.get()
        audit.record(
            "run",
            actor,
            {
                "config_file": cfg.governance.external_config_path or ".env/default",
                "workspace": str(layout.root),
            },
        )
        interactive_main()
        return 0

    if args.command == "dashboard":
        from flow_agent.app.bootstrap import create_app_runtime

        cfg = settings.get()
        _, _, server, _, _, _ = create_app_runtime()
        server.start()
        print(f"dashboard started on {cfg.channels.dashboard_host}:{cfg.channels.dashboard_port}")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.stop()
            print("dashboard stopped")
        return 0

    if args.command == "runtime":
        if args.runtime_action in {"start", "stop", "restart", "reload"}:
            _ensure_allowed(security, role, f"runtime.{args.runtime_action}")
        from flow_agent.app.bootstrap import create_app_runtime

        _, _, _, _, _, runtime_service = create_app_runtime()
        if args.runtime_action == "snapshot":
            print(json.dumps(asdict(runtime_service.snapshot()), ensure_ascii=False, indent=2))
        elif args.runtime_action == "health":
            rows = [asdict(item) for item in runtime_service.health_check()]
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.runtime_action == "start":
            for name in ("proactive", "dashboard"):
                runtime_service.start(name)
            audit.record("runtime.start", actor, {"targets": ["proactive", "dashboard"]})
            print("runtime start applied for proactive/dashboard")
        elif args.runtime_action == "stop":
            for name in ("proactive", "dashboard"):
                runtime_service.stop(name)
            audit.record("runtime.stop", actor, {"targets": ["proactive", "dashboard"]})
            print("runtime stop applied for proactive/dashboard")
        elif args.runtime_action == "restart":
            for name in ("proactive", "dashboard"):
                runtime_service.stop(name)
                runtime_service.start(name)
            audit.record("runtime.restart", actor, {"targets": ["proactive", "dashboard"]})
            print("runtime restart applied for proactive/dashboard")
        elif args.runtime_action == "reload":
            cfg = settings.reload()
            audit.record(
                "runtime.reload",
                actor,
                {"config_file": cfg.governance.external_config_path or ".env/default"},
            )
            print(
                "runtime reload complete with "
                f"config_file={cfg.governance.external_config_path or '.env/default'}"
            )
        return 0

    if args.command == "jobs" and args.jobs_action == "list":
        from flow_agent.app.bootstrap import create_background_runtime

        runtime = create_background_runtime()
        metrics.inc("jobs.list")
        print(json.dumps(runtime.registry.list_names(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "channels" and args.channels_action == "list":
        cfg = settings.get()
        payload = {
            "cli_enabled": cfg.channels.cli_enabled,
            "http_enabled": cfg.channels.http_enabled,
            "dashboard_enabled": cfg.channels.dashboard_enabled,
            "qq_enabled": cfg.channels.qq_enabled,
            "http_host": cfg.channels.http_host,
            "http_port": cfg.channels.http_port,
            "dashboard_host": cfg.channels.dashboard_host,
            "dashboard_port": cfg.channels.dashboard_port,
            "qq_host": cfg.channels.qq_host,
            "qq_port": cfg.channels.qq_port,
            "qq_api_base": cfg.channels.qq_api_base,
            "qqbot_app_id": cfg.channels.qqbot_app_id[:8] + "***" if cfg.channels.qqbot_app_id else "",
            "qqbot_configured": bool(cfg.channels.qqbot_app_id and cfg.channels.qqbot_token),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "sources" and args.sources_action == "list":
        cfg = settings.get()
        payload = {
            "memory_followup": True,
            "local_todo": cfg.proactive.todo_file,
            "file_feed": cfg.proactive.source_file,
            "rss_feed": cfg.proactive.rss_feed_files or [],
            "web_fetch": cfg.proactive.web_snapshot_files or [],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "skills":
        manager = SkillManager(layout.skills_dir)
        if args.skills_action == "list":
            print(json.dumps([item.to_dict() for item in manager.scan()], ensure_ascii=False, indent=2))
        elif args.skills_action == "install":
            _ensure_allowed(security, role, "skills.install")
            manifest = manager.install(Path(args.path))
            audit.record("skills.install", actor, {"name": manifest.name, "version": manifest.version})
            print(f"skill installed: {manifest.name}@{manifest.version}")
        elif args.skills_action == "enable":
            _ensure_allowed(security, role, "skills.enable")
            manager.enable(args.name)
            audit.record("skills.enable", actor, {"name": args.name})
            print(f"skill enabled: {args.name}")
        elif args.skills_action == "disable":
            _ensure_allowed(security, role, "skills.disable")
            manager.disable(args.name)
            audit.record("skills.disable", actor, {"name": args.name})
            print(f"skill disabled: {args.name}")
        return 0

    if args.command == "plugins":
        manager = PluginManager(layout.plugins_dir)
        if args.plugins_action == "list":
            print(json.dumps([item.to_dict() for item in manager.scan()], ensure_ascii=False, indent=2))
        elif args.plugins_action == "install":
            _ensure_allowed(security, role, "plugins.install")
            manifest = manager.install(Path(args.path))
            audit.record("plugins.install", actor, {"name": manifest.name, "version": manifest.version})
            print(f"plugin installed: {manifest.name}@{manifest.version}")
        elif args.plugins_action == "uninstall":
            _ensure_allowed(security, role, "plugins.uninstall")
            manager.uninstall(args.name)
            audit.record("plugins.uninstall", actor, {"name": args.name})
            print(f"plugin uninstalled: {args.name}")
        elif args.plugins_action == "enable":
            _ensure_allowed(security, role, "plugins.enable")
            manager.enable(args.name)
            audit.record("plugins.enable", actor, {"name": args.name})
            print(f"plugin enabled: {args.name}")
        elif args.plugins_action == "disable":
            _ensure_allowed(security, role, "plugins.disable")
            manager.disable(args.name)
            audit.record("plugins.disable", actor, {"name": args.name})
            print(f"plugin disabled: {args.name}")
        return 0

    if args.command == "marketplace":
        installer = MarketplaceInstaller(
            index=MarketplaceIndex(layout.data_dir / "marketplace-index.json"),
            skills=SkillManager(layout.skills_dir),
            plugins=PluginManager(layout.plugins_dir),
        )
        if args.market_action == "rebuild":
            rows = installer.rebuild_local_index()
            audit.record("marketplace.rebuild", actor, {"count": len(rows)})
            print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
        elif args.market_action == "list":
            rows = installer.index.load()
            print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


def _ensure_allowed(security: SecurityPolicy, role: str, action: str) -> None:
    allowed, reason = security.check_command(role=role, action=action)
    if not allowed:
        raise PermissionError(reason)
