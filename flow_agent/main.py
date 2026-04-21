import logging

from flow_agent.app.bootstrap import create_orchestrator
from flow_agent.config.loader import load_settings


logger = logging.getLogger(__name__)

def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        orchestrator = create_orchestrator()
    except ValueError:
        logger.exception("Failed to initialize agent due to invalid configuration")
        print("初始化失败：请检查 .env 中的 API Key 配置。")
        return

    print("Flow Agent CLI")
    print("Enter 'exit' to quit")
    print("Use '/session <id>' to switch session")
    current_session = settings.session.default_session_id

    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        if user_input.startswith("/session "):
            new_session = user_input.removeprefix("/session ").strip()
            if not new_session:
                print("Agent: 会话ID不能为空。")
                continue
            current_session = new_session
            print(f"Agent: 已切换到会话 {current_session}")
            continue
        try:
            response = orchestrator.run_turn(user_input, session_id=current_session)
        except Exception:
            logger.exception("Unexpected error during agent run")
            print("Agent: 处理请求时发生异常，请稍后再试。")
            continue
        print(f"Agent: {response.content}")


if __name__ == "__main__":
    main()
