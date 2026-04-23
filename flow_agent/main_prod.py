import os

from flow_agent.main import main


def run() -> None:
    os.environ.setdefault("FLOW_AGENT_PROFILE", "prod")
    os.environ.setdefault("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "true")
    os.environ.setdefault("FLOW_AGENT_CHANNEL_DASHBOARD_ENABLED", "true")
    main()


if __name__ == "__main__":
    run()

