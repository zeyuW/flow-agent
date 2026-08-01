# DDD 四层架构重构设计

状态：已确认

日期：2026-08-01

## 1. 文档目的

本文定义项目从现有按技术能力分包的结构，重构为 `src/` 下四个顶层包的目标架构。重构采用 DDD 的领域建模思想和分层依赖规则，以业务能力作为 Domain 与 Application 内部的主要拆分轴。

本次重构必须保留现有产品能力，但不保留旧 Python 导入路径、内部接口、配置结构、数据库结构或插件扩展 API 的兼容性。重构不得通过长期兼容层维持旧设计。

本文是总体架构规格。实际实施按可独立验证的阶段推进，每一阶段补充对应的需求和任务清单，并在进入下一阶段前通过相关测试与全量回归。

## 2. 目标与非目标

### 2.1 目标

- 在 `src/` 下建立 `domain`、`application`、`infra`、`interfaces` 四个顶层 Python 包。
- Domain 只包含业务事实、状态和规则，不依赖框架、网络、数据库、文件系统或其他三层。
- Application 以被动对话、主动交互、委托、后台作业、定时调度等业务用例组织编排。
- Infra 实现 Application 声明的端口，承载 LLM、存储、消息、执行器和外部服务客户端。
- Interfaces 负责外部请求进入系统，包括 CLI、HTTP、Telegram、QQ 和 MCP Server。
- 保留所有现有产品能力、并发语义、失败语义、热更新能力和可靠投递行为。
- 消除现有静态导入环，并用自动化架构测试阻止新循环和反向依赖。
- 缩小组合根、回合管线、消息总线、插件加载器和主动循环等超大组件的职责范围。
- 使用通俗、一致的业务名称，避免重复分层和含义含混的通用目录。

### 2.2 非目标

- 不把每个类机械建模为实体、值对象或聚合。
- 不为简单 CRUD、SDK 包装器或纯技术工具强行引入领域模型。
- 不在本轮增加新的用户功能、渠道或第三方集成。
- 不承诺迁移旧配置格式、旧数据库记录、旧插件声明或外部 Python 导入路径。
- 不把整个项目拆成微服务；目标形态仍是可独立部署的模块化单体。
- 不引入依赖注入框架、全局服务定位器或运行时自动扫描容器。

## 3. 设计原则

### 3.1 依赖方向

允许的静态依赖如下：

```text
interfaces ──────> application ──────> domain
     │                  ▲                 ▲
     └──────> infra ────┴─────────────────┘
```

- `domain` 不得导入 `application`、`infra` 或 `interfaces`。
- `application` 不得导入 `infra` 或 `interfaces`。
- `infra` 可以导入 `application` 中的端口和 DTO，也可以导入 `domain` 中的类型。
- `interfaces` 可以导入 Application 的命令、查询和结果 DTO；组合根可以额外导入 Infra 具体实现。
- Domain 内各业务包默认不得互相导入。跨领域协作由 Application 显式编排或通过领域事件完成。
- Application 内不同业务流程不得直接调用彼此的私有 Handler。共用能力应抽成公开用例服务或端口。

### 3.2 高内聚与低耦合

- 同一业务能力在 Domain 和 Application 中使用相同的通用语言命名。
- Application 的端口与使用它们的业务流程放在一起，避免全局 `ports/` 变成杂物目录。
- Infra 按技术适配器组织，但每个实现必须明确对应哪个 Application Port。
- 跨层传递不可变 DTO 或领域事件，不共享运行时可变对象。
- Domain 方法同步执行且无 I/O；Application 用例以异步接口统一编排外部 I/O。

### 3.3 简洁性约束

- 小业务包不强制创建空的 `entities.py`、`services.py` 或 `repositories.py`。
- 只有存在稳定身份和生命周期的对象才建模为实体或聚合。
- 只有需要被替换、隔离测试或跨越 I/O 边界的依赖才声明端口。
- 禁止创建 `common`、`utils`、`manager` 等没有明确业务含义的聚合目录。
- 组合根使用显式构造函数完成依赖装配，不使用隐藏的全局注册或运行期属性注入。

## 4. 目标目录结构

```text
src/
├── domain/
│   ├── conversation/
│   │   ├── models.py
│   │   ├── events.py
│   │   └── policies.py
│   ├── proactive/
│   │   ├── models.py
│   │   ├── events.py
│   │   └── policies.py
│   ├── delegation/
│   │   ├── models.py
│   │   ├── events.py
│   │   └── policies.py
│   ├── jobs/
│   │   ├── models.py
│   │   ├── events.py
│   │   └── policies.py
│   ├── scheduling/
│   │   ├── models.py
│   │   └── policies.py
│   ├── memory/
│   │   ├── models.py
│   │   └── policies.py
│   ├── delivery/
│   │   ├── models.py
│   │   ├── events.py
│   │   └── policies.py
│   └── capabilities/
│       ├── models.py
│       └── policies.py
├── application/
│   ├── conversation/
│   │   ├── commands.py
│   │   ├── handlers.py
│   │   ├── ports.py
│   │   └── dto.py
│   ├── proactive/
│   │   ├── commands.py
│   │   ├── handlers.py
│   │   ├── ports.py
│   │   └── dto.py
│   ├── delegation/
│   │   ├── commands.py
│   │   ├── handlers.py
│   │   ├── ports.py
│   │   └── dto.py
│   ├── jobs/
│   │   ├── commands.py
│   │   ├── handlers.py
│   │   ├── ports.py
│   │   └── dto.py
│   ├── scheduling/
│   │   ├── commands.py
│   │   ├── handlers.py
│   │   ├── ports.py
│   │   └── dto.py
│   ├── memory/
│   ├── delivery/
│   └── capabilities/
├── infra/
│   ├── config/
│   │   ├── schema.py
│   │   ├── loader.py
│   │   └── watcher.py
│   ├── persistence/
│   │   ├── sqlite/
│   │   ├── vector/
│   │   └── markdown/
│   ├── llm/
│   │   ├── clients.py
│   │   ├── routing.py
│   │   ├── prompting.py
│   │   └── embedding.py
│   ├── messaging/
│   │   ├── event_bus.py
│   │   ├── message_bus.py
│   │   └── outbox.py
│   ├── execution/
│   │   ├── workers.py
│   │   ├── subagents.py
│   │   └── timers.py
│   ├── integrations/
│   │   ├── mcp_client.py
│   │   └── proactive_sources.py
│   ├── extensions/
│   │   ├── plugins.py
│   │   └── skills.py
│   ├── observability/
│   ├── security/
│   └── runtime/
└── interfaces/
    ├── bootstrap.py
    ├── cli.py
    ├── http.py
    ├── telegram.py
    ├── qq.py
    └── mcp_server.py
```

目录是目标职责图，不要求无条件创建所有文件。实施阶段只在对应职责出现时创建文件，避免生成空壳层。

项目采用多个直接位于 `src/` 下的顶层包，不再保留 `flow_agent` Python 包。构建配置必须把 `src` 声明为包根，并只发现 `domain*`、`application*`、`infra*`、`interfaces*`。CLI 入口调整为 `interfaces.cli:main`。由于这些包名较通用，CI 必须验证安装后的导入来源均属于本项目。

## 5. 业务领域划分

### 5.1 Conversation：对话

职责：表达会话、消息、回合、工具轨迹和回合提交规则。

主要模型：

- `ConversationId`、`MessageId`、`TurnId` 等值对象。
- `Message`：用户、助手、工具或系统消息。
- `Turn`：一次从输入到提交结果的生命周期。
- `Conversation`：维护同一会话的已提交消息和必要元数据。
- `TurnCommitted`：回合完成并可供记忆、观测和投递使用的事实。

Conversation 不负责调用 LLM、读取数据库、检索记忆或发送渠道消息。这些动作由 Application 编排并通过端口完成。

### 5.2 Proactive：主动交互

职责：表达何时、为何、向谁主动触达，以及频率、冷却、每日上限和空闲策略。

主要模型：

- `ProactiveSignal`：数据源、空闲状态或用户行为产生的候选信号。
- `ProactivePolicy`：启用状态、频控、冷却和兴趣主题。
- `ProactiveDecision`：发送、跳过或延迟，以及对应原因。
- `ProactiveApproved`：已通过领域规则、可以进入内容生成的事实。

Proactive 不直接拼装提示词，不读取渠道 SDK，也不直接发送消息。

### 5.3 Delegation：委托任务

职责：表达由智能体委托给子智能体的长任务及其状态转换。

主要模型：

- `DelegatedTask` 聚合。
- 状态：`queued`、`running`、`completed`、`failed`、`cancelled`。
- `DelegatedTaskCompleted` 与 `DelegatedTaskFailed` 领域事件。

委托任务完成后由 Application 决定如何续接原会话；Domain 不导入 Conversation 或 Delivery。

### 5.4 Jobs：后台作业

职责：表达一次后台工作单元的注册、排队、运行、重试、取消和运行记录。

`Job` 是工作单元，不是常驻线程。常驻线程、协程或进程统一称为 Worker，放在 `infra/execution/workers.py`。Jobs Domain 不感知具体执行方式。

### 5.5 Scheduling：定时调度

职责：表达何时触发提醒或创建工作项，包括 `after`、`at`、`daily`、`every` 规则、时区、下一次执行时间和取消规则。

Schedule 决定何时触发，不负责执行 Job，也不直接调用渠道。

### 5.6 Memory：记忆

职责：表达记忆条目、用户画像、去重、替代和保留规则。

向量索引、Markdown 文件、Embedding、SQLite 和 LLM 抽取属于 Infra；Application 负责检索、写入、整理和回合后处理编排。

### 5.7 Delivery：可靠投递

职责：表达出站投递、稳定投递标识、回执和可靠性状态。

状态至少保留 `prepared`、`sending`、`delivered`、`failed`、`unknown` 和 `expired`。结果未知时禁止自动重放，避免重复消息。

### 5.8 Capabilities：工具与扩展能力

职责：表达工具声明、风险等级、执行请求、插件贡献和可调用能力约束。

工具、插件、技能和 MCP 的发现与运行实现属于 Infra。Domain 只表达稳定的业务规则，Application 负责选择、守卫和执行编排。

## 6. Application 用例设计

### 6.1 被动对话

主入口：`HandleUserMessage`。

```text
Interface 入站
  -> HandleUserMessage
  -> 获取同会话执行权
  -> 读取会话与相关记忆
  -> 组装推理请求
  -> 执行 LLM 与受控工具循环
  -> 原子提交 Turn
  -> 发布 TurnCommitted
  -> 请求可靠投递
```

必须保持同会话 FIFO、跨会话并行。失败回合不得伪装成成功提交；可发送的错误回复仍经 Delivery 处理。

### 6.2 主动交互

主入口：`EvaluateProactiveOpportunity`。

```text
数据源或空闲信号
  -> EvaluateProactiveOpportunity
  -> Domain 频控、冷却、限额和忙碌判断
  -> 采集必要上下文
  -> 得到 ProactiveDecision
  -> ComposeProactiveMessage
  -> 请求可靠投递
```

主动流程只决定主动触达和生成主动内容，不伪造用户入站消息。主动消息与被动回复共享 LLM、记忆和 Delivery 端口，但不共享私有 Handler。

### 6.3 委托后台任务

主入口：`DelegateTask`、`HandleDelegatedTaskCompletion`。

```text
模型调用委托工具
  -> DelegateTask
  -> 创建 DelegatedTask
  -> TaskExecutor 启动子智能体
  -> 发布完成或失败事件
  -> HandleDelegatedTaskCompletion
  -> 续接原会话或形成结果消息
  -> 请求可靠投递
```

任务完成不得通过伪造普通用户输入绕过会话边界。完成事件必须携带稳定任务标识、来源会话和幂等键。

### 6.4 后台作业与定时调度

- Jobs 用例负责作业注册、入队、执行请求、重试、取消和运行历史。
- Scheduling 用例负责创建、查询、取消和触发计划。
- 到期提醒直接形成 Delivery 请求。
- 到期的 Agent 任务通过显式 Application Command 进入 Conversation，而不是构造渠道消息。
- Worker、Timer 和 Queue Consumer 是 Infra 实现，不进入 Domain。

## 7. 端口与适配器

Application 按业务流程声明以下类型的端口，具体名称在阶段计划中确定：

- 会话仓储与同会话执行协调器。
- LLM 推理、提示词渲染和 Embedding。
- 记忆读取、写入和维护。
- 工具目录、工具执行和风险守卫。
- 领域事件发布与工作消息传递。
- 可靠投递与回执更新。
- Job 仓储、Job Executor 和 Scheduler Clock。
- Delegated Task 仓储与 Subagent Executor。
- 主动数据源与主动状态仓储。
- 插件、技能和 MCP 能力目录。

端口返回业务可理解的结果或受控异常，不泄漏第三方 SDK 响应对象。Infra 在适配器边界完成异常翻译。

## 8. 配置设计

### 8.1 目标依赖

```text
config.toml
  -> infra.config.loader
  -> infra.config.schema
  -> interfaces.bootstrap
  -> 各组件所需的配置切片
```

当前 `config.settings -> config.loader -> llm.config -> config.settings` 静态导入环必须删除。

### 8.2 文件与职责

- `infra/config/schema.py`：定义不可变的 `AppConfig` 和嵌套 Pydantic 配置模型。
- `infra/config/loader.py`：使用 `tomllib` 或 Python 3.10 下的 `tomli` 读取 TOML，并直接执行 `AppConfig.model_validate(raw)`。
- `infra/config/watcher.py`：监视配置文件，加载并验证候选快照，调用显式应用回调。
- `interfaces/bootstrap.py`：启动时加载一次配置，并把最小配置切片注入具体组件。

删除 `ConfigValues`、LLM 配置二次 Builder、`_SettingsProxy` 和模块级 Settings Cache。Schema 不得导入 Loader，业务对象不得主动读取全局配置。

配置模型使用 `extra="forbid"` 捕获拼写错误，并使用不可变模型避免运行期被任意修改。跨字段约束由模型验证器处理。

### 8.3 热更新

Watcher 持有上一份已生效快照，并采用准备、提交两阶段更新：

1. 文件变化后加载候选配置。
2. 完整验证候选配置。
3. 计算只包含允许热更新字段的不可变 Patch。
4. 各运行单元执行 Prepare；该阶段可以验证或创建候选资源，但不得修改当前运行对象。
5. 所有 Prepare 成功后执行 Commit；Commit 只允许不会失败的字段赋值或原子引用交换。
6. Commit 完成后更新 Watcher 当前快照，并清理被替换资源。
7. Prepare 任一步骤失败都清理候选资源、保留旧运行对象和旧快照，并记录结构化错误。

需要重建模型客户端、渠道或存储连接的字段不得边重建边修改当前对象；由运行时先创建并验证新适配器，再执行原子引用交换，或明确要求重启。设计不接受“部分组件已更新、配置快照仍为旧值”的半提交状态。

`config.toml` 继续作为唯一外部配置源且不得提交凭据。仓库提供不含真实凭据的示例配置。配置文件只承载需要按部署调整的设置，不暴露无必要的内部实现细节。

## 9. 消息、事件与事务边界

- Domain Event 表达已经发生的业务事实，使用不可变数据结构。
- Application Command 表达希望执行的动作，只由一个明确 Handler 处理。
- MessageBus 是 Infra 工作消息机制，不进入 Domain。
- EventBus 是 Infra 领域事件发布实现，不替代 Application 编排。
- 回合提交和内部事件记录使用明确的本地事务边界。
- 外部渠道发送不能与本地数据库形成原子事务，继续使用 Outbox 和稳定投递标识协调。
- 不假设 EventBus 订阅者同步完成；需要可靠处理的后续动作必须持久化。

## 10. 错误与失败语义

- Domain 抛出只表达业务无效状态的领域异常。
- Application 将端口失败转换为用例级错误结果，并决定重试、跳过、降级或失败。
- Infra 捕获 SDK、文件系统、网络和数据库异常，在端口边界翻译为稳定错误类型。
- Interfaces 把 Application 结果映射为渠道响应、HTTP 状态或 CLI 退出状态。
- 永久错误不得重试；可重试错误使用有上限的退避策略；未知错误默认失败而不是盲目重试。
- 取消必须区分排队任务和正在执行任务，不能错误终止无关工作。
- 插件、MCP 或主动数据源局部失败不得无条件阻止基本被动对话启动。

## 11. 并发与生命周期

- Application 的 I/O 用例统一使用 `async`，Domain 保持同步纯计算。
- Conversation 维持每会话单写者：同会话 FIFO，跨会话并行。
- Jobs 的 Job 是工作单元，Worker 是 Infra 执行资源；最大队列与并发由配置控制。
- Proactive 单次 Tick 与插件贡献刷新必须互斥，避免读取半代配置。
- 插件热更新继续采用准备、校验、统一发布的两阶段流程；任一候选失败时保留当前代。
- 运行时关闭先停止接收新工作，再等待活跃任务，超时后执行受控取消和资源清理。
- 组合根返回具名 `ApplicationRuntime`，不再返回位置敏感的长元组。

## 12. 现有模块迁移映射

| 现有能力 | 目标位置 |
| --- | --- |
| `core`、`session`、`behavior` | `domain/conversation`、`application/conversation`、相关 Infra 适配器 |
| `proactive`、`drift` | `domain/proactive`、`application/proactive`、`infra/integrations` |
| `subagent` | `domain/delegation`、`application/delegation`、`infra/execution/subagents.py` |
| `background` | `domain/jobs`、`application/jobs`、`infra/execution/workers.py` |
| `scheduler` | `domain/scheduling`、`application/scheduling`、`infra/execution/timers.py` |
| `memory` | `domain/memory`、`application/memory`、`infra/persistence`、`infra/llm` |
| `messaging` | `domain/delivery`、`application/delivery`、`infra/messaging` |
| `tools` | `domain/capabilities`、`application/capabilities`、Infra 具体适配器 |
| `plugins`、`skills` | `infra/extensions`，通过 Capabilities 端口接入 |
| `mcp` | `infra/integrations/mcp_client.py` 与 `interfaces/mcp_server.py` |
| `channels` | `interfaces` 与 `infra/messaging` |
| `config`、`runtime`、`observe` | `infra/config`、`infra/runtime`、`infra/observability` |
| `security`、`guard` | `interfaces` 入站认证、Application 授权策略、Infra 具体实现 |
| `app/bootstrap.py`、`main.py` | `interfaces/bootstrap.py`、`interfaces/cli.py` |

## 13. 测试策略

### 13.1 架构测试

新增静态架构测试，至少验证：

- 四个顶层包之间只出现允许的依赖方向。
- Domain 不导入第三方 SDK、Pydantic、SQLite、文件系统适配器或其他层。
- Domain 业务包之间没有静态循环。
- Application 不导入 Infra 或 Interfaces。
- 全项目内部导入图没有强连通分量大于 1 的循环。
- 安装后 `domain`、`application`、`infra`、`interfaces` 的来源路径均属于当前项目。
- 当前项目不泄露禁止出现的外部来源名称、路径或标识。

### 13.2 分层测试

- Domain：纯单元测试，覆盖状态转换、策略边界和领域事件。
- Application：使用 Fake Port 测试用例顺序、分支、幂等和错误处理。
- Infra：对仓储、Outbox、LLM/MCP 适配器和配置加载执行契约测试。
- Interfaces：测试协议转换、认证、输入校验和结果映射。
- 集成：覆盖被动回复、主动交互、委托任务、Jobs、Scheduling、记忆和插件热更新。

### 13.3 回归门禁

- 当前基线为 238 个测试全部通过。
- 每个迁移阶段先补失败测试，再完成最小实现。
- 阶段完成时运行最小相关测试和全量 `pytest`。
- 运行 Pyright、Black 检查、`git diff --check`、来源隔离扫描和工作区状态检查。
- 不以删除失败测试、降低断言或屏蔽类型错误作为重构完成手段。

## 14. 分阶段迁移

### 阶段 1：架构骨架与配置

- 建立 `src/` 包根、四层包和架构测试。
- 实现单向配置加载，删除现有配置导入环。
- 建立具名组合根和最小运行时容器。
- 保持现有主程序可启动，并明确新旧代码的临时边界。

### 阶段 2：Delivery 与 Conversation 主链

- 迁移消息模型、可靠投递和 Outbox。
- 迁移会话、回合、同会话执行协调与被动回复用例。
- 拆分当前超大回合管线，保持工具调用和流式事件能力。

### 阶段 3：Memory 与 Capabilities

- 分离记忆领域规则、记忆用例与持久化/LLM 实现。
- 迁移工具目录、守卫、插件、技能和 MCP 能力接入。
- 保持插件两阶段热更新与工具风险控制。

### 阶段 4：Jobs、Scheduling 与 Delegation

- 区分 Job、Worker、Schedule 和 DelegatedTask。
- 迁移后台可靠性、重试、取消、恢复和运行记录。
- 迁移子智能体执行与完成后续接会话。

### 阶段 5：Proactive 与外部接入

- 迁移主动策略、数据源、判断、Drift 和主动生命周期。
- 迁移 CLI、HTTP、Telegram、QQ 与 MCP Server。
- 用新组合根替代旧 Bootstrap，删除旧包和临时边界。

### 阶段 6：收尾与文档

- 删除未引用旧代码、兼容别名和重复配置路径。
- 更新架构、功能和时序文档。
- 执行完整验证并确认只保留目标四层结构。

每个阶段都必须生成可运行、可测试的结果。若一个阶段无法保持基本产品能力，应进一步拆小，不得扩大为一次性重写。

## 15. 验收标准

- `src/` 下业务代码只存在 `domain`、`application`、`infra`、`interfaces` 四个顶层包。
- 所有现有产品能力均有对应的新用例和回归测试。
- 全项目静态内部导入图无循环。
- `domain` 与 `application` 满足依赖规则，违规导入会使 CI 失败。
- 配置只通过 `config.toml -> loader -> schema -> bootstrap` 单向加载。
- 不存在全局 Settings Proxy、全局服务定位器或模块级可变依赖容器。
- 被动对话保持同会话 FIFO、跨会话并行和工具调用能力。
- 主动交互保持准入、采集、判断、解析、投递和 Drift 能力。
- Jobs、Scheduling 和 Delegation 保持各自的持久化、恢复、重试、取消与结果处理语义。
- Outbox 继续区分明确失败与结果未知，未知结果不自动重放。
- 插件与主动贡献热更新继续使用准备后统一发布的安全语义。
- 全量测试、类型检查、格式检查、来源隔离检查和空白检查通过。

## 16. 已确认的关键决策

- 使用顶层四层结构，不采用限界上下文作为顶层目录。
- 删除 `flow_agent` Python 包，直接以 `src` 作为四个包的包根。
- Domain 存放纯业务规则，Application 负责主动、被动、委托和后台任务等流程编排。
- 外部请求进入系统的适配器放 Interfaces；系统主动调用的第三方客户端放 Infra。
- 使用 `conversation`、`proactive`、`delegation`、`jobs`、`scheduling` 等通俗业务名称。
- `Job` 表示工作单元，`Worker` 表示常驻执行资源，`Schedule` 表示时间规则。
- 配置采用单一 `config.toml`、单一 Schema 和单一 Loader 的单向设计。
- 保留全部产品能力，但不建立旧接口、配置、存储或扩展 API 的长期兼容层。
