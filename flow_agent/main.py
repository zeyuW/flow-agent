import logging

from flow_agent.app.bootstrap import create_app_runtime
from flow_agent.config.settings import settings
from flow_agent.infra.logging import configure_logging
from flow_agent.channels.http import HTTPChannel
from flow_agent.channels.telegram import TelegramChannel
from flow_agent.tools.message_push import MessagePushTool


logger = logging.getLogger(__name__)

def main() -> None:
    cfg = settings.get()
    configure_logging("INFO")
    print(
        "Config summary: "
        f"http_enabled={cfg.channels.http_enabled}, "
        f"dashboard_enabled={cfg.channels.dashboard_enabled}, "
        f"jobs_queue={cfg.jobs.max_async_queue}, "
        f"subagent_max={cfg.subagent.max_concurrency}"
    )

    try:
        (
            orchestrator,
            proactive_runtime,
            dashboard_server,
            background_runtime,
            subagent_runtime,
            runtime_service,
            message_bus,
            event_bus,
            agent_loop,
            pipeline,
            tool_registry,
            *_,
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
    if cfg.channels.telegram_enabled and telegram:
        import threading
        import asyncio
        def run_telegram():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # 启动渠道后保持事件循环运行
            loop.run_until_complete(telegram.start(channel_ctx))
            # start 方法会创建轮询任务，这里需要保持循环运行
            loop.run_forever()
        telegram_thread = threading.Thread(target=run_telegram, daemon=True)
        telegram_thread.start()
        print("telegram channel started")
    
    # 启动其他渠道
    if cfg.channels.dashboard_enabled:
        dashboard_server.start()
    if cfg.channels.http_enabled:
        http.start()

    # 启动 Agent 主循环（后台线程）
    agent_loop.start_background()

    # 启动主动回复循环（后台任务）
    if proactive_runtime:
        import asyncio
        import threading
        def run_proactive():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(proactive_runtime.start_background())
            loop.run_forever()
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
        if telegram:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(telegram.stop())
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
