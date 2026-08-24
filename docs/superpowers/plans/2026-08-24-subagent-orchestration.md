# Subagent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 参考 DeerFlow 2.0，实现 Lead Agent 通过 `task` 工具委派隔离 Subagent，并接收结构化结果继续生成最终回复。

**Architecture:** Lead Agent 只通过工具调用委派；`SubagentExecutor` 负责独立上下文、profile 工具、执行限制和结果转换；`SubagentManager` 负责任务生命周期、持久化和调度。后台通知与同步工具结果保持分离。

**Tech Stack:** Python 3.11+、pytest、现有 ToolRegistry、MessageBus、JsonlTaskStore、LLM client。

**Spec:** `docs/superpowers/specs/2026-08-24-subagent-orchestration-design.md`

## Global Constraints

- 不新增模型供应商或外部 Agent SDK。
- Subagent 默认不继承完整主会话历史。
- Subagent 默认不能递归调用 `task`。
- 所有委派必须受最大轮数、超时、结果长度和并发限制约束。
- 修改行为必须先写失败测试，再写实现。
- 不提交 Git，由用户自行提交。

---

### Task 1: 定义 Subagent 结果协议

**Files:**
- Modify: `backend/src/application/delegation/app/models.py`
- Test: `backend/tests/delegation/test_subagent_models.py`

- [x] 新增 `SubagentResult`，字段为 `task_id`、`status`、`summary`、`error`、`steps`。
- [x] 约束状态为 `completed`、`failed`、`timed_out`、`cancelled`。
- [x] 为结果序列化和失败状态添加测试。

### Task 2: 抽出 SubagentExecutor

**Files:**
- Create: `backend/src/application/delegation/app/executor.py`
- Modify: `backend/src/application/delegation/app/manager.py`
- Test: `backend/tests/delegation/test_subagent_executor.py`

- [x] 将 profile 构建、Subagent 执行和 `JobRunResult` 转换收敛到执行器。
- [x] 执行器接收 `task_id`、`description`、`profile`、`context`、`max_turns` 和 `timeout`。
- [x] 子 Agent 初始消息只包含任务和显式上下文。
- [x] 超时、模型异常、最大轮数分别转换为结构化失败结果。
- [x] 使用替身 LLM 验证正常结果、工具循环和失败结果。

### Task 3: 实现 Lead Agent 的 task 工具

**Files:**
- Create: `backend/src/application/delegation/app/task_tool.py`
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/src/application/passive/app/reasoning.py`
- Test: `backend/tests/delegation/test_task_tool.py`

- [x] 工具名称固定为 `task`，输入包含 `description`、`profile`、`context`、`max_turns`、`timeout`。
- [x] 工具调用同步等待执行器结果，并以紧凑文本返回给 Lead Agent。
- [x] 失败结果不能抛出未处理异常，必须返回可供 Lead Agent 继续判断的错误信息。
- [x] 注入会话元数据但不注入完整历史。
- [x] 在工具注册表中注册 `task`，并确保 Subagent 工具注册表不包含 `task`。
- [x] 测试主 Agent 工具循环收到结果后可以继续生成最终文本。

### Task 4: 增加委派限制和生命周期记录

**Files:**
- Modify: `backend/src/application/delegation/app/manager.py`
- Modify: `backend/src/application/delegation/infra/store.py`
- Modify: `backend/src/infra/config.py`
- Test: `backend/tests/delegation/test_task_limits.py`

- [x] 增加单次运行最大 Subagent 数、最大并发数、默认超时和默认最大轮数配置。
- [x] 在创建任务前拒绝超过额度的委派。
- [x] 记录 `started`、`running`、终态事件，并保留 `task_id` 与父 trace 关联。
- [x] 测试并发超限、总量超限、超时和重复完成事件。

### Task 5: 接入现有运行时和后台任务边界

**Files:**
- Modify: `backend/src/application/delegation/app/runtime.py`
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/src/bootstrap/service_app.py`
- Test: `backend/tests/infrastructure/test_service_app_lifecycle.py`

- [x] 通过统一 runtime 创建 `TaskTool` 所需的 Executor/Manager。
- [x] 保证服务停止时取消运行中的 Subagent 并关闭 worker。
- [x] 保留现有后台消息总线完成通知，但不让同步 `task` 依赖用户消息回流。
- [x] 验证初始化、启动、停止顺序和异常关闭路径。

### Task 6: 更新文档和端到端验证

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/ARCHITECTURE.md`
- Test: `backend/tests/integration/test_subagent_flow.py`

- [x] 记录 `task` 工具输入、结果状态、上下文隔离和限制语义。
- [x] 增加主 Agent → task → Subagent → 主 Agent 汇总的集成测试。
- [x] 验证 Subagent 不可递归委派，失败可被主 Agent 处理。
- [x] 运行 MCP、delegation、integration 和完整测试分组。
