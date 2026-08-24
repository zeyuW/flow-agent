# Subagent 编排设计

## 目标

参考 DeerFlow 2.0，将 Subagent 建模为主 Agent 可调用的 `task` 工具：主 Agent 决定是否委派，Subagent 在隔离上下文中执行，结果回到主 Agent 后由主 Agent 继续推理并生成最终回复。

## 核心流程

```text
用户请求
  ↓
Lead Agent 推理
  ├─ 直接使用现有工具
  └─ 调用 task(description, profile, context)
        ↓
  SubagentExecutor
        ├─ 校验委派额度
        ├─ 创建独立 Subagent 上下文
        ├─ 注入 profile 对应工具
        ├─ 执行模型与工具循环
        └─ 返回 SubagentResult
              ↓
        Lead Agent 的 ToolResult
              ↓
        Lead Agent 汇总并输出
```

首版允许一个 Lead Agent 回合内多次调用 `task`，运行时负责并发限制；是否并行由工具调用和执行器决定，不由业务层硬编码任务图。

## 运行边界

- Subagent 不继承完整聊天历史，只接收任务描述、显式上下文和必要的会话元数据。
- Subagent 使用 profile 对应的工具白名单；首版至少支持 `research` 和 `general`。
- Subagent 默认不能再次调用 `task`，防止递归扩散。
- 每个任务有最大轮数、超时和结果长度限制。
- 结果统一为 `SubagentResult`，至少包含 `status`、`summary`、`error`、`steps` 和 `task_id`。
- 子任务生命周期记录 `started`、`running`、`completed`、`failed`、`timed_out` 事件。
- 长任务可沿用消息总线通知原会话；主 Agent 的同步工具结果和后台通知是两条明确路径。

## 方案取舍

### 采用：Subagent 作为工具

主 Agent 保留最终回答权，Subagent 只完成边界清晰的子任务。这与 DeerFlow 2.0 的 `task()` → `SubagentExecutor` → 结构化结果路径一致，也能直接接入现有工具调用循环。

### 不采用：handoff

handoff 会把当前对话控制权交给 Subagent，适合专业 Agent 直接接管对话；Flow Agent 需要主 Agent 组合结果、控制权限和统一回复，因此不作为首版主路径。

### 不采用：独立意图识别 Agent

主 Agent 已经具备工具选择和任务理解能力。额外增加一个意图识别模型会增加延迟、状态同步和失败面，首版让主 Agent 通过 `task` 工具自主委派。

### 不采用：预定义固定任务图

当前需求是通用委派，不是固定研究流程。任务图会限制能力并增加编排代码；需要稳定流程时再在 Skill 或业务用例中增加显式 workflow。

## 与现有代码的关系

- `SubAgent` 保留模型与工具循环职责。
- `SubagentManager` 收敛为任务生命周期和执行调度入口。
- 新增或重构 `TaskTool`，作为 Lead Agent 的委派工具。
- 新增 `SubagentExecutor` 和 `SubagentResult`，隔离执行、状态和结果协议。
- 现有 `SpawnTool` 的后台通知能力不作为同步委派接口；后台任务能力后续单独命名和收敛。
- 复用现有任务存储、消息总线、trace 和运行时关闭流程。

## 参考

- [DeerFlow 2.0 官方仓库](https://github.com/bytedance/deer-flow)
- [DeerFlow 后端 Subagent 说明](https://github.com/bytedance/deer-flow/blob/main/backend/README.md)

