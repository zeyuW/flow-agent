import logging

from flow_agent.app.bootstrap import create_app_runtime
from flow_agent.config.loader import load_settings
from flow_agent.infra.logging import configure_logging
from flow_agent.channels.cli import CLIChannel
from flow_agent.channels.http import HTTPChannel
from flow_agent.channels.models import OutboundMessage, InboundMessage


logger = logging.getLogger(__name__)

def main() -> None:
    settings = load_settings()
    configure_logging(settings.logging.level)

    try:
        orchestrator, proactive_runtime, dashboard_server, background_runtime, subagent_runtime = create_app_runtime()
    except ValueError:
        logger.exception("Failed to initialize agent due to invalid configuration")
        print("初始化失败：请检查 .env 中的 API Key 配置。")
        return

    print("Flow Agent CLI")
    print("Enter 'exit' to quit")
    print("Use '/session <id>' to switch session")
    print("Use '/proactive tick|start|stop|status' to control proactive runtime")
    print("Use '/dashboard start|stop' to control dashboard server")
    print("Use '/http start|stop' to control http channel")
    current_session = settings.session.default_session_id

    def handle_inbound(msg: InboundMessage) -> OutboundMessage:
        response = orchestrator.run_turn(msg.text, session_id=msg.session_id)
        return OutboundMessage(channel=msg.channel, session_id=msg.session_id, text=response.content)

    cli = CLIChannel(handler=handle_inbound, default_session_id=current_session)
    http = HTTPChannel(host="127.0.0.1", port=8788, handler=handle_inbound)
    cli.start()

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
                print("Agent: dashboard started on 127.0.0.1:8787")
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
                print("Agent: http channel started on 127.0.0.1:8788")
            elif cmd == "stop":
                http.stop()
                print("Agent: http channel stopped")
            else:
                print("Agent: http command should be start|stop")
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
