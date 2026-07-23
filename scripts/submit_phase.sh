#!/usr/bin/env bash
set -euo pipefail

# 按阶段选择文件和测试，减少 Agent 提交时的参数负担。
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PUSH_FLAG=""
if [[ "${1:-}" == "--push" ]]; then
  PUSH_FLAG="--push"
  shift
fi

PHASE="${1:-}"
case "${PHASE}" in
  phase1)
    SUMMARY="feat: 完善事件总线生命周期管理"
    DETAILS=$'增加事件订阅和取消订阅能力
补充事件总线生命周期测试'
    TEST_TARGET="tests/test_event_bus_lifecycle.py"
    FILES=(
      flow_agent/messaging/event_bus.py
      flow_agent/messaging/__init__.py
      tests/test_event_bus_lifecycle.py
    )
    ;;
  phase2)
    SUMMARY="feat: 增加上下文持久化与任务恢复能力"
    DETAILS=$'增加会话上下文持久化
增加任务状态和错误分类
增加重试与恢复语义
补充阶段二状态恢复测试'
    TEST_TARGET="tests/test_phase2_state_recovery.py"
    FILES=(
      flow_agent/background/runtime.py
      flow_agent/background/store.py
      flow_agent/background/tools.py
      flow_agent/core/agent.py
      flow_agent/core/context.py
      flow_agent/core/passive_turn_pipeline.py
      flow_agent/runtime/errors.py
      flow_agent/runtime/retry.py
      flow_agent/runtime/__init__.py
      flow_agent/scheduler/runtime.py
      flow_agent/session/session_manager.py
      flow_agent/session/session_store.py
      tests/test_phase2_state_recovery.py
    )
    ;;
  phase3)
    SUMMARY="feat: 完善出站消息可靠投递与恢复策略"
    DETAILS=$'增加出站消息持久化和幂等投递
增加运行期间失败退避重试
禁止启动时批量恢复历史消息
补充出站恢复和重复投递测试'
    TEST_TARGET="tests/test_reliable_delivery.py tests/test_phase3_boundaries.py tests/test_proactive_tick.py tests/test_spawn_runtime.py"
    FILES=(
      flow_agent/app/bootstrap.py
      flow_agent/channels/models.py
      flow_agent/channels/telegram.py
      flow_agent/core/agent_loop.py
      flow_agent/messaging/message_bus.py
      flow_agent/messaging/outbox.py
      flow_agent/proactive/deliver.py
      flow_agent/runtime/workspace.py
      flow_agent/config/loader.py
      flow_agent/config/settings.py
      flow_agent/subagent/manager.py
      flow_agent/subagent/models.py
      flow_agent/tools/spawn.py
      tests/test_proactive_tick.py
      tests/test_spawn_runtime.py
      tests/test_phase3_boundaries.py
      tests/test_reliable_delivery.py
    )
    ;;
  automation)
    SUMMARY="chore: 建立自动验证提交与 CI 流程"
    DETAILS=$'增加统一验证脚本
增加 Agent 自动生成提交说明和自动提交
增加提交前检查和 GitHub Actions CI'
    TEST_TARGET="tests/test_reliable_delivery.py"
    FILES=(
      .github/workflows/ci.yml
      .githooks/pre-commit
      scripts/agent_finish.sh
      scripts/install_hooks.sh
      scripts/submit_phase.sh
      scripts/verify.sh
      docs/automation.md
    )
    ;;
  *)
    echo "用法: scripts/submit_phase.sh [--push] phase1|phase2|phase3|automation"
    exit 2
    ;;
esac

for path in "${FILES[@]}"; do
  if [[ ! -e "${path}" ]]; then
    echo "阶段文件不存在: ${path}"
    exit 2
  fi
done

PUSH_ARGS=()
if [[ -n "${PUSH_FLAG}" ]]; then
  PUSH_ARGS=("${PUSH_FLAG}")
fi

FLOW_AGENT_TEST_TARGET="${TEST_TARGET}"   scripts/agent_finish.sh "${PUSH_ARGS[@]}"   --summary "${SUMMARY}"   --details "${DETAILS}"   "${FILES[@]}"
