import logging

from flow_agent.app.bootstrap import create_app_runtime
from flow_agent.config.settings import settings
from flow_agent.infra.logging import configure_logging
from flow_agent.channels.cli import CLIChannel
from flow_agent.channels.http import HTTPChannel
from flow_agent.channels.qq import QQChannel
from flow_agent.proactive.dispatcher import QQProactiveDispatcher


logger = logging.getLogger(__name__)

def main() -> None:
    cfg = settings.get()
    configure_logging(cfg.logging.level)
    print(
        "Config summary: "
        f"version={cfg.governance.config_version}, "
        f"config_file={cfg.governance.external_config_path or '.env/default'}, "
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
        ) = create_app_runtime()
    except ValueError:
        logger.exception("Failed to initialize agent due to invalid configuration")
        print("初始化失败：请检查 .env 中的 API Key 配置。")
        return

    print("Flow Agent CLI (MessageBus 架构)")
    print("Enter 'exit' to quit")
    print("Use '/session <id>' to switch session")
    print("Use '/proactive tick|start|stop|status' to control proactive runtime")
    print("Use '/dashboard start|stop' to control dashboard server")
    print("Use '/http start|stop' to control http channel")
    print("Use '/qq start|stop|status' to control qq channel")
    print("Use '/runtime snapshot|health' to inspect unified runtime")
    print("Use '/bus status' to inspect MessageBus/EventBus")
    current_session = cfg.session.default_session_id

    # 创建渠道并连接到 MessageBus
    cli = CLIChannel(
        message_bus=message_bus,
        default_session_id=current_session,
    )
    http = HTTPChannel(
        host=cfg.channels.http_host,
        port=cfg.channels.http_port,
        message_bus=message_bus,
    )
    qq = QQChannel(
        host=cfg.channels.qq_host,
        port=cfg.channels.qq_port,
        message_bus=message_bus,
        api_base=cfg.channels.qq_api_base,
        access_token=cfg.channels.qq_access_token,
    )

    # QQ 主动推送
    if cfg.proactive.qq_target_user_id.strip().isdigit():
        proactive_runtime.tick_runner.dispatcher = QQProactiveDispatcher(
            qq_user_id=int(cfg.proactive.qq_target_user_id.strip()),
            send_private_msg=qq._send_private_msg,
        )

    # 启动 Agent 主循环（后台线程）
    agent_loop.start_background()

    # 启动渠道
    cli.start()
    if cfg.channels.dashboard_enabled:
        dashboard_server.start()
    if cfg.channels.http_enabled:
        http.start()
    if cfg.channels.qq_enabled:
        qq.start()

    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        if user_input.startswith("/proactive "):
            cmd = user_input.removeprefix("/proactive ").strip().lower()
            if cmd == "tick":
                result = proactive_runtime.tick_runner.tick()
                print(f"Agent: proactive tick -> {result.reason}")
            elif cmd == "start":
                proactive_runtime.scheduler.start()
                print("Agent: proactive scheduler started")
            elif cmd == "stop":
                proactive_runtime.scheduler.stop()
                print("Agent: proactive scheduler stopped")
            elif cmd == "status":
                s = proactive_runtime.scheduler.status()
                print(
                    "Agent: "
                    f"running={s.running}, executing={s.is_executing}, "
                    f"last_started_at={s.last_started_at}, last_finished_at={s.last_finished_at}"
                )
            else:
                print("Agent: proactive command should be tick|start|stop|status")
            continue
        if user_input.startswith("/dashboard "):
            cmd = user_input.removeprefix("/dashboard ").strip().lower()
            if cmd == "start":
                dashboard_server.start()
                print(
                    f"Agent: dashboard started on {cfg.channels.dashboard_host}:{cfg.channels.dashboard_port}"
                )
            elif cmd == "stop":
                dashboard_server.stop()
                print("Agent: dashboard stopped")
            else:
                print("Agent: dashboard command should be start|stop")
            continue
        if user_input.startswith("/http "):
            cmd = user_input.removeprefix("/http ").strip().lower()
            if cmd == "start":
                http.start()
                print(
                    f"Agent: http channel started on {cfg.channels.http_host}:{cfg.channels.http_port}"
                )
            elif cmd == "stop":
                http.stop()
                print("Agent: http channel stopped")
            else:
                print("Agent: http command should be start|stop")
            continue
        if user_input.startswith("/qq "):
            cmd = user_input.removeprefix("/qq ").strip().lower()
            if cmd == "start":
                qq.start()
                print(f"Agent: qq channel started on {cfg.channels.qq_host}:{cfg.channels.qq_port}")
            elif cmd == "stop":
                qq.stop()
                print("Agent: qq channel stopped")
            elif cmd == "status":
                s = qq.status()
                print(f"Agent: qq channel running={s.running}, last_error={s.last_error}")
            else:
                print("Agent: qq command should be start|stop|status")
            continue
        if user_input.startswith("/runtime "):
            cmd = user_input.removeprefix("/runtime ").strip().lower()
            if cmd == "snapshot":
                snap = runtime_service.snapshot()
                print(f"Agent: runtime snapshot -> metrics={snap.metrics}, events={snap.event_summary}")
            elif cmd == "health":
                rows = runtime_service.health_check()
                print(
                    "Agent: runtime health -> "
                    + ", ".join(f"{row.name}:{'ok' if row.ok else 'bad'}" for row in rows)
                )
            else:
                print("Agent: runtime command should be snapshot|health")
            continue
        if user_input.startswith("/bus "):
            cmd = user_input.removeprefix("/bus ").strip().lower()
            if cmd == "status":
                print(
                    f"MessageBus: inbound_queue_size={message_bus.inbound.size}, "
                    f"outbound_subscribers={message_bus.outbound.subscriber_count}, "
                    f"EventBus: subscribers={event_bus.subscriber_count}, "
                    f"AgentLoop: running={agent_loop.running}"
                )
            else:
                print("Agent: bus command should be status")
            continue
        if user_input.startswith("/session "):
            new_session = user_input.removeprefix("/session ").strip()
            if not new_session:
                print("Agent: 会话ID不能为空。")
                continue
            current_session = new_session
            cli.default_session_id = current_session
            print(f"Agent: 已切换到会话 {current_session}")
            continue
        try:
            reply = cli.handle_line(user_input, session_id=current_session)
        except Exception:
            logger.exception("Unexpected error during agent run")
            print("Agent: 处理请求时发生异常，请稍后再试。")
            continue
        print(f"Agent: {reply or ''}")


if __name__ == "__main__":
    main()