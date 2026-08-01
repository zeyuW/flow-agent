from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from bootstrap.config import load_application_config
from bootstrap.service import run_service
from flow_agent.runtime.workspace import init_workspace

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _build_parser() -> argparse.ArgumentParser:
    """构建进程入口参数。"""

    parser = argparse.ArgumentParser(prog="flow-agent")
    commands = parser.add_subparsers(dest="command")
    init_parser = commands.add_parser("init", help="初始化 .flow 运行时工作区")
    init_parser.add_argument("--workspace", default=".", help="项目根目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """初始化工作区，或加载一次配置后启动服务。"""

    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "init":
        workspace = Path(args.workspace).expanduser().resolve()
        layout = init_workspace(workspace)
        print(f"工作区已初始化：{layout.flow_dir}")
        return 0

    try:
        config = load_application_config(BACKEND_ROOT)
    except (OSError, ValueError) as exc:
        print(f"启动失败：无法加载 backend/config.toml：{exc}")
        return 2
    run_service(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
