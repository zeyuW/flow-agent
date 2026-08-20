"""根目录联调启动脚本的行为测试。"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _wait_for(path: Path, process: subprocess.Popen[bytes]) -> None:
    """等待替身进程记录启动信息，避免测试依赖固定睡眠时间。"""

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(process.stderr.read().decode())
        time.sleep(0.05)
    raise AssertionError(f"进程未在期限内启动: {path.name}")


def _create_project(tmp_path: Path, *, frontend_dependencies: bool) -> Path:
    """创建供启动脚本运行的最小项目副本。"""

    project_root = tmp_path / "project"
    (project_root / "scripts").mkdir(parents=True)
    (project_root / "backend").mkdir()
    (project_root / "frontend").mkdir()
    for name in ("dev.sh", "start.sh"):
        shutil.copy2(PROJECT_ROOT / "scripts" / name, project_root / "scripts" / name)
    if frontend_dependencies:
        next_binary = project_root / "frontend/node_modules/.bin/next"
        next_binary.parent.mkdir(parents=True)
        next_binary.touch()
    return project_root


def _create_fake_commands(bin_dir: Path) -> None:
    """替换外部运行时，保留启动脚本自身的真实行为。"""

    for name, content in {
        "uv": '#!/usr/bin/env bash\nprintf "%s" "$*" > "$TEST_LOG_DIR/backend"\ntrap "exit 0" TERM INT\nwhile true; do sleep 1; done\n',
        "npm": '#!/usr/bin/env bash\nif [ "$*" = "ci" ]; then\n  printf "%s" "$*" > "$TEST_LOG_DIR/install"\n  exit 0\nfi\nprintf "%s|%s|%s" "$PWD" "$ADMIN_API_BASE_URL" "$*" > "$TEST_LOG_DIR/frontend"\ntrap "exit 0" TERM INT\nwhile true; do sleep 1; done\n',
        "xdg-open": '#!/usr/bin/env bash\nprintf "%s" "$*" > "$TEST_LOG_DIR/browser"\n',
    }.items():
        executable = bin_dir / name
        executable.write_text(content)
        executable.chmod(0o755)


def _start_dev_script(project_root: Path, log_dir: Path) -> subprocess.Popen[bytes]:
    bin_dir = log_dir.parent / "bin"
    bin_dir.mkdir()
    _create_fake_commands(bin_dir)
    environment = os.environ | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TEST_LOG_DIR": str(log_dir),
    }
    return subprocess.Popen(
        [project_root / "scripts" / "dev.sh"],
        cwd=project_root,
        env=environment,
        stderr=subprocess.PIPE,
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    process.wait(timeout=5)


def test_dev_script_starts_backend_and_frontend_when_dependencies_exist(
    tmp_path: Path,
) -> None:
    """依赖已安装时，联调脚本应同时启动后端和前端。"""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    project_root = _create_project(tmp_path, frontend_dependencies=True)
    process = _start_dev_script(project_root, log_dir)
    try:
        _wait_for(log_dir / "backend", process)
        _wait_for(log_dir / "frontend", process)
    finally:
        _stop(process)

    assert (log_dir / "backend").read_text() == "run python -m bootstrap.main"
    assert (log_dir / "frontend").read_text() == (
        f"{project_root / 'frontend'}|http://127.0.0.1:8790|run dev"
    )


def test_dev_script_installs_frontend_dependencies_when_missing(tmp_path: Path) -> None:
    """缺少 Next.js 本地命令时，联调脚本应先安装前端依赖。"""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    project_root = _create_project(tmp_path, frontend_dependencies=False)
    process = _start_dev_script(project_root, log_dir)
    try:
        _wait_for(log_dir / "frontend", process)
    finally:
        _stop(process)

    assert (log_dir / "install").read_text() == "ci"


def test_dev_script_opens_frontend_in_browser(tmp_path: Path) -> None:
    """前端启动后，联调脚本应在浏览器中打开其本机地址。"""

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    project_root = _create_project(tmp_path, frontend_dependencies=True)
    process = _start_dev_script(project_root, log_dir)
    try:
        _wait_for(log_dir / "browser", process)
    finally:
        _stop(process)

    assert (log_dir / "browser").read_text() == "http://localhost:3000"
