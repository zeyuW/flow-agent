# 模块化 DDD 重构架构设计

状态：已确认

版本：2.0

更新日期：2026-08-02

## 1. 文档目的

本文固化项目重构后的目录、模块边界、依赖方向和运行线路，是后续开发、测试、代码评审和迁移计划的统一依据。

目标架构采用两级拆分：仓库根目录先按可独立构建的产品划分为 `backend/` 与 `frontend/`；Python 后端内部再按业务模块划分，每个复杂业务模块根据实际需要包含 `domain/`、`application/` 和 `infra/`。外部接入、共享技术设施和进程装配分别放在 `interfaces/`、`infra/` 与 `bootstrap/`。

本次重构必须保留现有产品能力，但不保留旧 Python 导入路径、内部接口、配置结构、存储结构或扩展 API 的兼容性。迁移期间可以存在短期旧包，最终结构不得保留长期兼容层。

## 2. 核心结论

- 使用“业务模块优先、模块内部再分层”，不使用全局 `domain/application/infra` 三个巨型业务目录。
- 保留 Python 的 `backend/src` 布局，隔离可导入包与工程文件。
- `domain` 只表达业务状态、事实和规则；不得依赖框架、网络、文件系统、数据库或具体 SDK。
- `application` 负责一个业务用例的编排、事务边界、幂等、权限和失败策略。
- 模块内部 `infra` 实现该模块声明的仓储、RPC、消息和外部能力端口。
- 全局 `infra` 只提供不带具体业务语义的技术设施。
- `interfaces` 是系统边界，负责 HTTP、CLI、MCP 和第三方 IM 渠道的协议适配。
- `bootstrap` 是唯一组合根，负责配置加载、依赖装配、进程启动和有序关闭。
- 目标形态是模块化单体，不为目录美观强行拆成微服务。

## 3. 仓库目标结构

```text
flow-agent/
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── README.md
│   ├── config.example.toml
│   ├── src/
│   │   ├── modules/
│   │   │   ├── conversation/
│   │   │   │   ├── domain/
│   │   │   │   ├── application/
│   │   │   │   └── infra/
│   │   │   ├── proactive/
│   │   │   │   ├── domain/
│   │   │   │   ├── application/
│   │   │   │   └── infra/
│   │   │   ├── delegation/
│   │   │   │   ├── domain/
│   │   │   │   ├── application/
│   │   │   │   └── infra/
│   │   │   ├── jobs/
│   │   │   │   ├── domain/
│   │   │   │   ├── application/
│   │   │   │   └── infra/
│   │   │   ├── scheduling/
│   │   │   ├── memory/
│   │   │   ├── delivery/
│   │   │   └── capabilities/
│   │   ├── interfaces/
│   │   │   ├── http/
│   │   │   ├── cli/
│   │   │   ├── mcp/
│   │   │   └── channels/
│   │   │       ├── feishu/
│   │   │       ├── telegram/
│   │   │       └── wechat/
│   │   ├── infra/
│   │   │   ├── config/
│   │   │   ├── database/
│   │   │   ├── messaging/
│   │   │   ├── llm/
│   │   │   ├── observability/
│   │   │   ├── concurrency/
│   │   │   └── security/
│   │   └── bootstrap/
│   │       ├── container.py
│   │       ├── api.py
│   │       ├── worker.py
│   │       └── cli.py
│   └── tests/
│       ├── architecture/
│       ├── unit/
│       │   └── modules/
│       ├── integration/
│       └── contract/
├── frontend/
├── docs/
├── scripts/
├── skills/
└── deploy/
```

该目录是职责边界，不要求预先创建所有空目录。只有迁入实际代码或测试时才创建对应包。

## 4. 目录职责

### 4.1 `backend/src/modules`

`modules` 是后端业务代码的第一拆分轴。一个模块应当：

- 使用产品和业务人员能够理解的名称。
- 拥有明确的状态、规则、用例或生命周期。
- 能够独立阅读和独立测试。
- 不直接访问其他模块的私有实现。
- 不因某个第三方 SDK 或数据库表而成立。

复杂模块内部按需分为：

```text
<module>/
├── domain/          # 实体、值对象、领域服务、领域事件、端口抽象
├── application/     # 命令、查询、用例、事务和流程编排
└── infra/           # 本模块的仓储、消息、外部服务和持久化适配器
```

小模块不强制建立空的三层目录。一个只有少量纯规则的模块可以先保持扁平，在复杂度出现后再拆分。

### 4.2 `backend/src/interfaces`

`interfaces` 负责系统与外界之间的协议转换，包括：

- 自有 HTTP API、WebSocket 和 Webhook。
- CLI 命令及退出状态映射。
- MCP Server 接入。
- 飞书、Telegram、微信等第三方 IM 渠道。

Interfaces 可以把外部 DTO 转换为 Application Command，也可以把 Application Result 转换为外部响应，但不得包含回复决策、频控、任务状态转换或记忆规则。

### 4.3 `backend/src/infra`

全局 `infra` 只放共享的技术原语：

- 配置 Schema、Loader 与 Watcher。
- 数据库连接、事务原语和迁移工具。
- 通用消息队列、事件总线和 Outbox 原语。
- LLM、Embedding 和模型供应商客户端。
- 日志、指标和 Trace 基础设施。
- 锁、队列、线程、协程与取消原语。
- 密钥读取和通用安全设施。

全局 Infra 不得出现 `ConversationRepository`、`DelegatedTaskConsumer` 等具体业务名称；这些实现属于对应模块内部的 `infra`。

### 4.4 `backend/src/bootstrap`

`bootstrap` 是唯一允许同时导入 Interfaces、Modules 和 Infra 具体实现的目录，负责：

- 加载并验证配置。
- 创建数据库、LLM、消息、渠道和模块对象。
- 把端口绑定到具体适配器。
- 启动 API、Worker 或 CLI 进程。
- 处理信号、有序停止和资源清理。

业务代码不得导入 `bootstrap`。

## 5. 模块边界

### 5.1 Conversation：对话

表达会话、消息、回合、工具轨迹和回合提交规则。被动回复是 Conversation 的应用用例，不是独立领域。

建议用例：

- `HandleIncomingMessage`
- `ContinueConversation`
- `CommitTurn`
- `CancelTurn`

必须保持同一会话 FIFO、不同会话并行。失败回合不得伪装为成功提交。

### 5.2 Proactive：主动交互

表达何时、为何、向谁主动触达，以及冷却、每日上限、忙碌状态和兴趣策略。

建议用例：

- `EvaluateProactiveOpportunity`
- `ComposeProactiveMessage`
- `RecordProactiveOutcome`

主动消息不得伪造成普通用户输入。

### 5.3 Delegation：委托任务

表达 Agent 委托给子 Agent 的长任务及其业务状态：`queued`、`running`、`completed`、`failed`、`cancelled`。

委托完成后，由 Application 通过稳定任务标识、来源会话和幂等键续接原会话；不得构造虚假用户消息绕过会话边界。

### 5.4 Jobs：后台作业

表达可持久化工作单元的注册、排队、运行、重试、取消和运行记录。

- `Job` 是工作单元。
- `Worker` 是持续运行的执行资源。
- `Consumer` 是从消息来源领取 Job 的适配器。
- `Schedule` 是时间规则。

Worker 和 Consumer 放在模块 Infra 或 Bootstrap，不放在 Domain。

### 5.5 Scheduling：定时调度

表达 `after`、`at`、`daily`、`every`、时区、下一次触发和取消规则。Schedule 决定何时触发，不执行 Job，也不直接发送渠道消息。

### 5.6 Memory：记忆

表达记忆条目、用户画像、去重、替代、保留和召回规则。向量索引、Embedding、Markdown、SQLite 和具体模型调用是基础设施实现。

### 5.7 Delivery：可靠投递

表达出站投递、幂等标识、回执和可靠性状态。至少保留 `prepared`、`sending`、`delivered`、`failed`、`unknown` 和 `expired`。结果未知时禁止自动重放。

### 5.8 Capabilities：工具与扩展能力

表达工具声明、风险等级、执行请求、插件贡献和可调用约束。插件、技能和 MCP 的发现与运行属于适配器；领域层只保留稳定业务规则。

## 6. 第三方 IM 渠道规范

`interfaces/channels` 负责接入飞书、Telegram、微信等第三方 IM。每个平台按渠道聚合，避免一个平台的接收和发送代码散落在不同全局目录。

```text
interfaces/channels/
├── registry.py                  # 显式注册可用渠道
├── feishu/
│   ├── webhook.py               # 接收、鉴权和解析飞书事件
│   ├── sender.py                # 将统一投递请求转换为飞书请求
│   ├── schemas.py               # 飞书协议 DTO
│   ├── converter.py             # 外部 DTO 与内部消息互转
│   └── auth.py                  # 签名和令牌处理
├── telegram/
│   ├── webhook.py
│   ├── sender.py
│   ├── schemas.py
│   └── converter.py
└── wechat/
    ├── webhook.py
    ├── sender.py
    ├── schemas.py
    ├── converter.py
    └── auth.py
```

通用 HTTP Client、连接池、重试和限流放在全局 Infra；平台 URL、事件格式、签名和消息转换留在具体渠道包。

业务层只接触统一消息类型，不得出现第三方 SDK 对象。`IncomingMessage` 由 `modules/conversation/application` 定义，`DeliveryRequest` 和 `ChannelSender` 端口由 `modules/delivery/application` 定义，不得把这些稳定协议定义在 Interfaces 中：

```text
IncomingMessage
├── channel
├── conversation_id
├── sender_id
├── content
├── attachments
└── metadata

DeliveryRequest
├── channel
├── target_id
├── content
├── idempotency_key
└── reply_to
```

具体渠道 Sender 实现 `ChannelSender` 端口，由 Bootstrap 注入 Delivery 用例；Application 不反向导入任何渠道包。

渠道元数据只允许保存无法标准化但确实需要回传的值；业务判断不得依赖任意第三方原始字典。

## 7. 三条核心运行线路

### 7.1 被动回复

```text
第三方 IM / HTTP / CLI
  -> interfaces 入站适配器
  -> Conversation.HandleIncomingMessage
  -> 获取同会话执行权
  -> 读取会话与相关记忆
  -> 执行 LLM 与受控工具循环
  -> 原子提交 Turn
  -> 发布 TurnCommitted
  -> Delivery 请求
  -> interfaces/channels sender
```

### 7.2 主动回复

```text
定时信号 / 空闲信号 / 主动数据源
  -> Proactive.EvaluateProactiveOpportunity
  -> 频控、冷却、限额和忙碌判断
  -> 采集必要上下文
  -> ComposeProactiveMessage
  -> Delivery 请求
  -> interfaces/channels sender
```

主动与被动线路共享 LLM、Memory、Capabilities 和 Delivery 端口，但不互相调用私有 Handler。

### 7.3 委托后台任务

```text
Conversation 中的委托请求
  -> Delegation.DelegateTask
  -> 创建 DelegatedTask 和 Job
  -> 消息队列或本地持久队列
  -> bootstrap.worker
  -> Delegation 模块 Consumer
  -> ExecuteDelegatedTask
  -> 发布完成或失败事件
  -> HandleDelegatedTaskCompletion
  -> 续接 Conversation
  -> Delivery 请求
```

## 8. 依赖规则

### 8.1 模块内部

```text
interfaces ─────> module.application ─────> module.domain
                         ▲                       ▲
                         │                       │
module.infra ────────────┴───────────────────────┘

bootstrap ─────> interfaces + modules + infra
```

- `domain` 不得导入本模块 Application、Infra、Interfaces 或 Bootstrap。
- `application` 不得导入具体 Infra、Interfaces 或 Bootstrap。
- 模块 Infra 可以导入本模块 Domain 与 Application 中声明的端口。
- Interfaces 只能调用模块公开 Application 用例，不得直接访问仓储实现。
- Bootstrap 可以导入所有具体实现，但不得包含业务规则。

### 8.2 跨模块

- 一个模块不得导入另一个模块的 `domain`、`infra` 或私有 Application 文件。
- 同步协作优先由调用方声明 Port，并在组合根绑定适配器。
- 已发生的业务事实使用不可变领域事件传播。
- 需要可靠处理的事件必须持久化，不能依赖仅存在于内存的同步订阅。
- 跨模块静态依赖必须单向，架构测试拒绝任何循环。

### 8.3 禁止项

- 禁止 `domain -> infra`、`domain -> application` 和 `application -> infra`。
- 禁止模块在导入时读取配置或创建网络客户端。
- 禁止全局服务定位器、Settings Proxy 和模块级可变依赖容器。
- 禁止 `common/`、`utils/`、`pkg/` 成为无边界杂物目录。
- 禁止把第三方 DTO、ORM Model 或 SDK Exception 泄漏进 Domain。

## 9. 配置设计

唯一配置依赖链：

```text
backend/config.toml
  -> infra.config.loader
  -> infra.config.schema
  -> bootstrap
  -> 各组件需要的最小配置切片
```

- `schema.py` 定义不可变、拒绝未知字段的嵌套配置模型。
- `loader.py` 只读取调用方传入的一个 TOML 文件，不搜索备用路径，不读取 YAML，不隐式合并环境变量。
- `watcher.py` 使用 Prepare/Commit 两阶段热更新；准备失败时保留旧快照和旧运行对象。
- 需要重建客户端的配置先创建并验证候选资源，再原子交换引用。
- 删除旧配置代理、二次 Builder 和模块缓存，消除配置静态导入环。

## 10. 事件、错误与可靠性

- Domain Event 表达已经发生的事实；Application Command 表达希望执行的动作。
- Application 决定事务、幂等、重试、降级和失败结果。
- Infra 在适配器边界把 SDK、数据库和网络异常翻译为稳定端口错误。
- Interfaces 把应用结果映射为 HTTP、CLI 或渠道协议结果。
- 永久错误不重试；可重试错误使用有上限退避；未知错误默认失败。
- 外部渠道发送通过 Outbox 和稳定投递标识协调，不能假设与本地数据库原子提交。
- 运行时关闭顺序为：停止接收新工作、等待活跃工作、超时后受控取消、清理资源。

## 11. 测试与架构门禁

- Domain 使用纯单元测试，不启动数据库、网络或事件循环。
- Application 使用 Fake Port 验证编排顺序、幂等、失败分支和事务语义。
- 模块 Infra 使用仓储、消息和外部适配器契约测试。
- Interfaces 测试协议转换、认证、输入校验和返回映射。
- 集成测试覆盖被动回复、主动回复、委托任务、Jobs、Scheduling、Memory 和可靠投递。
- 静态导入图必须无循环，并检查模块内分层和跨模块依赖规则。
- 每个迁移阶段先补失败测试，再完成最小实现，最后运行全量回归。

当前基线为 238 个测试通过。不得通过删除测试、降低断言或屏蔽错误完成重构。

## 12. 迁移原则与阶段

### 阶段 1：仓库布局、架构门禁与配置

- 建立 `backend/src`、`backend/tests` 和模块化包根。
- 将旧实现机械移动到迁移期包，不同时改写全部业务。
- 建立静态导入图和模块依赖测试。
- 实现单一 TOML 配置和显式注入，删除配置导入环。

### 阶段 2：Delivery 与 Conversation

- 先迁移可靠投递、Outbox 和渠道统一协议。
- 再迁移会话、回合、并发控制和被动回复主链。

### 阶段 3：Memory 与 Capabilities

- 迁移记忆规则、检索、整理和持久化适配器。
- 迁移工具、插件、技能和 MCP 能力边界。

### 阶段 4：Jobs、Scheduling 与 Delegation

- 区分 Job、Worker、Consumer、Schedule 和 DelegatedTask。
- 迁移持久化、恢复、重试、取消和委托结果续接。

### 阶段 5：Proactive 与 Interfaces

- 迁移主动策略、主动数据源和主动消息生成。
- 迁移 HTTP、CLI、MCP 以及现有第三方 IM 渠道。

### 阶段 6：删除旧包与工程收尾

- 删除迁移期旧包、兼容别名和重复配置路径。
- 完成前后端构建、部署脚本和开发文档整理。
- 执行全量测试、类型、格式、来源隔离和空白检查。

每个阶段必须交付可启动、可测试的工作版本，不进行不可验证的一次性重写。

## 13. 验收标准

- 仓库根目录以 `backend/`、`frontend/` 和工程支撑目录组织。
- Python 后端代码只从 `backend/src` 导入。
- 业务以 `modules/<business>` 聚合，复杂模块内部按需包含 Domain、Application 和 Infra。
- 全局 Interfaces、Infra 和 Bootstrap 职责符合本文约束。
- 第三方 IM 代码按 `interfaces/channels/<platform>` 聚合，业务层只处理统一消息协议。
- 被动回复、主动回复和委托后台任务均遵循本文运行线路。
- 全项目静态内部导入图无循环，违规依赖会使 CI 失败。
- 配置只通过单一 TOML、单一 Schema、单一 Loader 和显式注入进入运行时。
- 所有现有产品能力都有对应新用例和回归测试。
- 不存在长期兼容层、全局配置代理或隐藏依赖装配。

## 14. 已确认决策

- 根目录采用 `backend/frontend` 产品边界。
- Python 后端保留 `backend/src`。
- DDD 采用业务模块优先，而不是全局四层优先。
- 业务模块使用 `conversation`、`proactive`、`delegation`、`jobs`、`scheduling`、`memory`、`delivery` 和 `capabilities`。
- 第三方 IM 接入统一放入 `interfaces/channels/<platform>`。
- 被动回复属于 Conversation 用例；主动回复属于 Proactive；委托长任务属于 Delegation。
- Job、Worker、Consumer 和 Schedule 使用不同术语表达不同职责。
- LLM 当前是配置驱动的共享技术能力，放在全局 Infra；只有未来出现用户可管理的模型业务时才升级为独立业务模块。
- 配置采用单一 TOML、单一 Schema、单一 Loader 和两阶段热更新。
- 保留全部产品能力，不保留旧内部结构的长期兼容性。
