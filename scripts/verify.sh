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
  read -r -a TEST_ARGS <<< "${FLOW_AGENT_TEST_TARGET}"
else
  TEST_ARGS=(
    tests/test_agent.py
    tests/test_chunked_decoder.py
    tests/test_drift.py
    tests/test_filesystem_tool.py
    tests/test_hawkes_proactive.py
    tests/test_history_builder.py
    tests/test_llm_streaming.py
    tests/test_mcp_runtime.py
    tests/test_memory.py
    tests/test_memory_autowrite.py
    tests/test_memory_maintenance.py
    tests/test_proactive_tick.py
    tests/test_scheduler.py
    tests/test_scheduler_tasks.py
    tests/test_stage11_external.py
    tests/test_stage15_behavior_strategy.py
    tests/test_stage16_memory_reasoning.py
    tests/test_stage18_workspace_commands.py
    tests/test_tool_registry.py
    tests/test_event_bus_lifecycle.py
    tests/test_phase2_state_recovery.py
    tests/test_phase3_boundaries.py
    tests/test_reliable_delivery.py
    tests/test_spawn_runtime.py
  )
fi
"${PYTHON_BIN}" -m pytest -q "${TEST_ARGS[@]}"

echo "验证通过"
