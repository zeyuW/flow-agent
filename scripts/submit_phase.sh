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
    TEST_TARGET="backend/tests/delivery/test_event_bus_lifecycle.py"
    FILES=(
      backend/src/infra/messaging/event_bus.py
      backend/src/infra/messaging/__init__.py
      backend/tests/delivery/test_event_bus_lifecycle.py
    )
    ;;
  phase2)
    SUMMARY="feat: 增加上下文持久化与任务恢复能力"
    DETAILS=$'增加会话上下文持久化
增加任务状态和错误分类
增加重试与恢复语义
补充阶段二状态恢复测试'
    TEST_TARGET="backend/tests/jobs/test_phase2_state_recovery.py"
    FILES=(
      backend/src/modules/jobs/application/runtime.py
      backend/src/modules/jobs/infra/store.py
      backend/src/modules/jobs/application/tools.py
      backend/src/modules/conversation/application/agent.py
      backend/src/modules/conversation/infra/context.py
      backend/src/modules/conversation/application/pipeline.py
      backend/src/infra/resilience/errors.py
      backend/src/infra/resilience/retry.py
      backend/src/infra/runtime/__init__.py
      backend/src/modules/scheduling/application/runtime.py
      backend/src/modules/conversation/infra/session_manager.py
      backend/src/modules/conversation/infra/session_store.py
      backend/tests/jobs/test_phase2_state_recovery.py
    )
    ;;
  phase3)
    SUMMARY="feat: 完善出站消息可靠投递与恢复策略"
    DETAILS=$'增加出站消息持久化和幂等投递
增加运行期间失败退避重试
禁止启动时批量恢复历史消息
补充出站恢复和重复投递测试'
    TEST_TARGET="backend/tests/delivery/test_reliable_delivery.py backend/tests/delivery/test_phase3_boundaries.py backend/tests/proactive/test_proactive_tick.py backend/tests/delegation/test_spawn_runtime.py"
    FILES=(
      backend/src/bootstrap/container.py
      backend/src/interfaces/channels/models.py
      backend/src/interfaces/channels/telegram.py
      backend/src/modules/conversation/application/agent_loop.py
      backend/src/modules/delivery/infra/delivery_bus.py
      backend/src/modules/delivery/infra/outbox.py
      backend/src/modules/proactive/application/deliver.py
      backend/src/infra/runtime/workspace.py
      backend/src/infra/config/loader.py
      backend/src/infra/config/schema.py
      backend/src/modules/delegation/application/manager.py
      backend/src/modules/delegation/application/models.py
      backend/src/modules/delegation/application/spawn.py
      backend/tests/proactive/test_proactive_tick.py
      backend/tests/delegation/test_spawn_runtime.py
      backend/tests/delivery/test_phase3_boundaries.py
      backend/tests/delivery/test_reliable_delivery.py
    )
    ;;
  automation)
    SUMMARY="chore: 建立自动验证提交与 CI 流程"
    DETAILS=$'增加统一验证脚本
增加 Agent 自动生成提交说明和自动提交
增加提交前检查和 GitHub Actions CI'
    TEST_TARGET="backend/tests/delivery/test_reliable_delivery.py"
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
