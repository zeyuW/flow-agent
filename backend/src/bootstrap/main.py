"""Flow Agent 进程入口。"""

from __future__ import annotations

import logging
from pathlib import Path

from bootstrap.config import load_application_config
from bootstrap.service_app import ServiceApp
from infra.workspace import WorkspaceAlreadyRunningError

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(project_root: Path = PROJECT_ROOT) -> None:
    """创建应用并负责进程级生命周期编排。"""

    app: ServiceApp | None = None
    try:
        config = load_application_config(project_root)
        app = ServiceApp(config)
        app.init()
        app.start()
        app.wait()
    except WorkspaceAlreadyRunningError as exc:
        print(f"启动失败：{exc}")
    except ValueError:
        logger.exception("Failed to initialize agent due to invalid configuration")
        print("初始化失败：请检查config.toml中的配置。")
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if app is not None:
            app.stop()


if __name__ == "__main__":
    main()
