import os

from flow_agent.main import main


def run() -> None:
    os.environ.setdefault("FLOW_AGENT_PROFILE", "dev")
    main()


if __name__ == "__main__":
    run()

