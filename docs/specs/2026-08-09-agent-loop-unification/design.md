# Agent Loop 与业务语义分层设计

## 状态

目录重构和被动入口循环已经实施。当前采用“通用 AgentLoop + 被动业务适配器”的结构，主动推送继续由 `proactive` 自己管理业务循环。

## 一、目录职责

```text
application/agent/app/loop.py
    通用 AgentLoop：消费、并发、FIFO、确认、失败重试和线程生命周期

application/passive/app/passive_loop.py
    被动语义适配器：将 MessageBus 消息转换为 IncomingMessage

application/passive/app/pipeline.py
    单次被动回合：六阶段流程和模型—工具循环
```

`AgentLoop` 不依赖 `passive`、`proactive` 或其他具体业务。业务模块通过消息转换器和处理器注入自己的语义，因此共享循环不会反向依赖业务模块。

## 二、被动消息链路

```text
渠道适配器
    ↓ 发布 InboundMessage
MessageBus
    ↓ 接收 ReceivedMessage
PassiveLoop
    ↓ 转换 IncomingMessage
AgentLoop
    ↓ 维持会话 FIFO，并行处理不同会话
PassiveTurnPipeline.process_async()
    ↓ 六个阶段
模型 ↔ Tool/MCP 循环
    ↓
MessageBus 出站投递
```

`AgentLoop` 负责：

- 消费统一消息协议；
- 同一会话串行处理；
- 不同会话并行处理；
- 成功 `ack`，失败 `nack(retry=True)`；
- 后台线程启动、停止和异步任务回收；
- 发布 `turn_started` 事件。

`PassiveLoop` 只负责被动业务消息转换，不复制并发和生命周期代码。

## 三、主动语义

主动推送不是被动消息消费的另一种输入格式，它拥有候选采集、判断、去重、冷却和投递策略，因此继续由 `application/proactive` 管理自己的业务循环。

主动流程可以复用 `application/agent` 中的 Agent 执行能力，但不能让 `agent` 反向导入 `proactive`。

## 四、Agent 执行能力

`application/agent` 包含被动、主动和委派流程共用的 Agent 能力：

- `app/agent.py`：模型调用、上下文组装和视觉模型路由；
- `app/loop.py`：通用消息循环；
- `domain/models.py`：Agent 响应模型；
- `domain/ports.py`：历史上下文端口；
- `domain/policies.py`：委派和安全处理策略。

MCP 由 `McpServerRegistry` 管理，并将工具注册到 `ToolRegistry`。Skills 仍由 `capabilities/skills` 管理，主动 Drift 技能和被动 Agent 技能保持各自的业务作用域。

## 五、组合根和生命周期

`bootstrap.container` 创建 `PassiveLoop`，`ServiceApp` 负责进程级生命周期：

```text
ServiceApp.start() → passive_loop.start_background()
ServiceApp.stop()  → passive_loop.stop_background()
```

`bootstrap.main` 负责工作区初始化、配置加载、`ServiceApp` 创建以及 `init → start → wait → stop` 生命周期。

## 六、依赖约束

```text
passive ──────┐
proactive ────┤
delegation ───┤──> agent ───> capabilities
schedule ─────┘

automation ───> capabilities + 顶层 infra
```

禁止以下依赖：

```text
agent → passive
agent → proactive
capabilities → proactive
passive → proactive
proactive → passive
```

架构测试会扫描 `application` 的导入图，确保不存在循环依赖。
