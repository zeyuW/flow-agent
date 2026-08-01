"""应用入口：初始化工作区或启动服务。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from flow_agent.app.bootstrap import create_app_runtime
from flow_agent.config.settings import settings
from flow_agent.infra.logging import configure_logging
from flow_agent.channels.http import HTTPChannel
from flow_agent.infra.paths import WORKSPACE_LAYOUT
from flow_agent.runtime.workspace import init_workspace
from flow_agent.channels.telegram import TelegramChannel
from flow_agent.tools.message_push import MessagePushTool
from flow_agent.runtime.workspace_lock import (
    WorkspaceAlreadyRunningError,
    WorkspaceProcessLock,
)


logger = logging.getLogger(__name__)


def run_service() -> None:
    """获取工作区唯一所有权后启动完整服务。"""

    lock = WorkspaceProcessLock(WORKSPACE_LAYOUT.flow_dir / "runtime.lock")
    try:
        lock.acquire()
    except WorkspaceAlreadyRunningError as exc:
        print(f"启动失败：{exc}")
        return
    try:
        _run_service()
    finally:
        lock.release()


def _run_service() -> None:
    cfg = settings.get()
    configure_logging(cfg.logging.level, WORKSPACE_LAYOUT.app_log_file)
    print(
        "Config summary: "
        f"http_enabled={cfg.channels.http_enabled}, "
        f"jobs_queue={cfg.jobs.max_async_queue}, "
        f"subagent_max={cfg.subagent.max_concurrency}"
    )

    try:
        (
            proactive_runtime,
            background_runtime,
            subagent_runtime,
            runtime_service,
            message_bus,
            event_bus,
            agent_loop,
            pipeline,
            tool_registry,
            memory_runtime,
            memory_optimizer_loop,
            mcp_registry,
            plugin_manager,
        ) = create_app_runtime()
    except ValueError:
        logger.exception("Failed to initialize agent due to invalid configuration")
        print("初始化失败：请检查config.toml中的配置。")
        return

    print("Flow Agent (MessageBus 架构)")
    print("Services starting...")

    # 创建渠道并连接到 MessageBus
    http = HTTPChannel(
        host=cfg.channels.http_host,
        port=cfg.channels.http_port,
        message_bus=message_bus,
    )

    # Telegram 渠道
    telegram = None
    if cfg.channels.telegram_bot_token:
        allowed_users = set()
        allowed_groups = set()
        if cfg.channels.telegram_allowed_users:
            allowed_users = {u.strip() for u in cfg.channels.telegram_allowed_users.split(",") if u.strip()}
        if cfg.channels.telegram_allowed_groups:
            allowed_groups = {int(g.strip()) for g in cfg.channels.telegram_allowed_groups.split(",") if g.strip().isdigit()}
        
        telegram = TelegramChannel(
            bot_token=cfg.channels.telegram_bot_token,
            allowed_users=list(allowed_users),
            allowed_groups=list(allowed_groups),
        )

        # 注册 MessagePushTool
        message_push = MessagePushTool()
        message_push.register_channel(
            "telegram",
            send=telegram.send,
            send_file=telegram.send_file,
            send_image=telegram.send_image,
        )
        tool_registry.register(message_push)

    # 启动渠道（先启动渠道，让它们订阅 MessageBus）
    from flow_agent.channels.protocol import ChannelContext
    
    # 创建渠道上下文
    channel_ctx = ChannelContext(
        bus=message_bus,
        event_bus=event_bus,
        log=logger,
    )
    
    # 启动 Telegram 渠道（使用新协议，在后台线程运行）
    telegram_thread = None
    telegram_loop_holder: dict[str, object] = {}
    if cfg.channels.telegram_enabled and telegram:
        import threading
        import asyncio
        def run_telegram():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            telegram_loop_holder["loop"] = loop
            try:
                # Telegram.start 会持续等待轮询任务，不需要额外 run_forever。
                loop.run_until_complete(telegram.start(channel_ctx))
            finally:
                telegram_loop_holder.pop("loop", None)
                loop.close()
        telegram_thread = threading.Thread(target=run_telegram, daemon=True)
        telegram_thread.start()
        print("telegram channel started")
    
    # 启动其他渠道
    if cfg.channels.http_enabled:
        http.start()

    # 启动 Agent 主循环（后台线程）
    agent_loop.start_background()

    background_runtime.start()
    print("scheduler started")

    if memory_optimizer_loop is not None:
        memory_optimizer_loop.start()
        print("memory optimizer started")

    # 启动主动回复循环（后台线程）
    proactive_thread = None
    if proactive_runtime:
        import asyncio
        import threading

        def run_proactive():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(proactive_runtime.run())
            finally:
                loop.close()

        proactive_thread = threading.Thread(target=run_proactive, daemon=True)
        proactive_thread.start()
        print("proactive loop started")

    # 等待 Telegram 渠道完成订阅（延迟启动 MessageBus 分发任务）
    import time
    time.sleep(1.0)  # 等待 1 秒确保渠道订阅完成

    # 启动 MessageBus 后台分发任务（后台线程）- 确保在所有渠道订阅后启动
    import threading
    import asyncio
    def run_dispatch():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(message_bus.start_dispatch_task())
    dispatch_thread = threading.Thread(target=run_dispatch, daemon=True)
    dispatch_thread.start()
    print("MessageBus dispatch task started")

    print("All services started. Press Ctrl+C to stop.")
    
    # 保持主线程运行
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        if proactive_runtime:
            proactive_runtime.request_stop()
        if memory_optimizer_loop is not None:
            memory_optimizer_loop.stop()
        background_runtime.stop()
        subagent_runtime.manager.shutdown()
        mcp_registry.stop_all()
        import asyncio
        asyncio.run(plugin_manager.shutdown_all())
        if proactive_thread is not None:
            proactive_thread.join(timeout=5.0)
        if telegram:
            loop = telegram_loop_holder.get("loop")
            if loop is not None and not loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(telegram.stop(), loop)
                try:
                    future.result(timeout=5.0)
                except Exception:
                    logger.exception("Telegram 渠道停止失败")
            if telegram_thread is not None:
                telegram_thread.join(timeout=8.0)
        print("Shutdown complete.")


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""

    parser = argparse.ArgumentParser(prog="flow-agent")
    commands = parser.add_subparsers(dest="command")
    init_parser = commands.add_parser("init", help="初始化 .flow 运行时工作区")
    init_parser.add_argument("--workspace", default=".", help="项目根目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行命令；无子命令时直接启动服务。"""

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        workspace = Path(args.workspace).expanduser().resolve()
        layout = init_workspace(workspace)
        print(f"工作区已初始化：{layout.flow_dir}")
        return 0

    run_service()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
