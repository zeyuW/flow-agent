#!/usr/bin/env bash
set -euo pipefail

# 统一执行本地验证，保证本地与 CI 使用同一套检查。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export TMPDIR="${TMPDIR:-/tmp}"

echo "[1/4] 编译源码"
"${PYTHON_BIN}" -m compileall -q flow_agent

echo "[2/4] 检查空白和冲突标记"
git diff --check
if git diff --check --cached; then
  :
else
  echo "暂存区存在空白错误"
  exit 1
fi

echo "[3/4] 检查项目隔离"
if rg -n -i 'akashic[-_ ]?agent|/home/roco/akashic-agent|参考项目|参考仓库' flow_agent tests; then
  echo "检测到不应出现在当前项目中的参考来源信息"
  exit 1
fi

echo "[4/4] 运行测试"
if [[ -n "${FLOW_AGENT_TEST_TARGET:-}" ]]; then
  # 显式指定时仅用于本地快速回归；CI 不设置此变量。
  read -r -a test_targets <<< "${FLOW_AGENT_TEST_TARGET}"
  "${PYTHON_BIN}" -m pytest -q "${test_targets[@]}"
else
  "${PYTHON_BIN}" -m pytest -q
fi

echo "验证通过"
