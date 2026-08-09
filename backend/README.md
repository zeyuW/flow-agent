# Flow Agent Backend

这是 Flow Agent 的 Python 后端。项目使用 `backend/src` 源码布局，运行时从四个顶层包访问业务、接口、共享基础设施和进程启动代码。

## 目录结构

```text
backend/
├── pyproject.toml       # Python 版本、依赖和工具配置
├── uv.lock              # 依赖锁定文件
├── src/
│   ├── application/     # 业务模块、应用用例和跨模块能力
│   ├── interfaces/      # HTTP、Telegram、QQ、CLI 等外部适配器
│   ├── infra/           # 跨业务共享的技术基础设施
│   └── bootstrap/       # 配置、依赖装配和进程生命周期
└── tests/               # 架构、单元、集成和端到端测试
```

### `application/`：业务模块

业务按语义边界组织，目标目录如下：

```text
application/
├── agent/                              # Agent 通用执行内核
│   ├── domain/                         # Agent 请求、结果、策略和端口
│   └── app/                            # Agent Turn、工具循环和 Prompt 组装
│
├── passive/                            # 被动语义：接收消息并回复
│   ├── domain/                         # 被动消息和会话领域模型
│   ├── app/                            # 被动回复用例和消息处理循环
│   └── infra/                          # 被动业务专属存储和适配实现
│
├── proactive/                          # 主动语义：发现内容并推送
│   ├── domain/                         # 主动推送状态、候选内容和策略
│   ├── app/                            # 采集、判断、去重和推送流程
│   └── infra/                          # 主动业务专属状态和存储实现
│
├── schedule/                           # 用户创建的定时任务
│   ├── domain/                         # 定时任务模型和触发规则
│   ├── app/                            # 创建、查询、取消和到期处理
│   └── infra/                          # 定时任务持久化实现
│
├── automation/                         # 系统和插件自动化作业
│   ├── domain/                         # 作业定义和运行记录
│   ├── app/                            # 注册、触发、重试和并发控制
│   └── infra/                          # 作业运行记录和写入实现
│
├── delegation/                         # 子 Agent 创建、委派和执行
│   ├── domain/                         # 委派任务和结果模型
│   ├── app/                            # 子 Agent 管理和执行流程
│   └── infra/                          # 委派业务专属外部实现
│
├── memory/                             # 记忆提取、检索、去重和整理
│   ├── domain/                         # 记忆领域模型和规则
│   ├── app/                            # 记忆业务用例
│   └── infra/                          # 向量库、文件和数据库实现
│
└── capabilities/                       # Agent 可复用的应用能力
    ├── llm/                            # LLM 客户端和模型适配
    ├── mcp/                            # MCP 服务发现和工具适配
    ├── skills/                         # Skill 加载、注册和匹配
    ├── tools/                          # Tool 定义、注册和执行
    ├── plugins/                        # 插件加载和生命周期管理
    └── behavior/                       # Agent 行为策略
```

复杂业务模块通常按以下职责划分：

```text
application/<feature>/
├── domain/      # 领域模型、状态、规则和领域事实
├── app/         # 用例编排、流程、事务边界和失败策略
└── infra/       # 仅属于该业务的存储和外部技术实现
```

`domain` 不读取配置、不操作数据库、不访问网络，也不依赖具体 SDK。`app` 负责把领域对象、应用能力和业务基础设施组织成完整用例。`application/<feature>/infra` 可以依赖本业务的 `domain`，用于实现业务专属的仓储、网关或持久化逻辑。

`agent` 是被动、主动和委派流程共同使用的 Agent 执行内核，只能依赖稳定的能力接口，不能反向依赖 `passive` 或 `proactive`。

`schedule` 表示用户创建的定时任务，例如提醒、定时执行 Agent；负责任务规则、时间计算、持久化和到期触发。

`automation` 表示系统或插件注册的自动化作业；负责作业注册、事件或间隔触发、并发控制、去重、重试和运行记录。它执行的是已注册的系统作业函数，不代表用户创建的定时任务。

`application/capabilities` 放置多个业务会共用的应用能力，例如 LLM、MCP、插件、技能和工具注册表；它仍然属于应用层，不是顶层共享 `infra`。

### `interfaces/`：外部适配器

这一层负责协议转换和渠道生命周期：接收外部消息、转换为应用可理解的消息模型，并通过消息总线发送应用输出。当前主要包括 Telegram、HTTP、QQ 和 CLI 渠道。

接口层可以依赖应用层的稳定消息模型，也可以依赖顶层 `infra` 提供的消息总线、安全策略和工作区路径；它不应直接操作某个业务模块的私有仓储。

### `infra/`：共享技术基础设施

顶层 `infra` 只放跨业务通用的技术能力，不包含具体业务规则，也不依赖 `application`、`interfaces` 或 `bootstrap`。

```text
infra/
├── bus/
│   ├── event.py       # 进程内事件发布与订阅
│   ├── message.py     # 入站、出站和可靠投递消息总线
│   ├── queues.py      # 线程安全消息队列
│   └── types.py       # 消息数据类型及发送/消费协议
├── config.py          # 配置模型、TOML 加载和热更新
├── persistence.py     # SQLite 数据库和通用 outbox
├── resilience.py      # 错误分类、重试和 fallback
├── runtime.py         # 运行单元、健康检查和运行时快照
├── security.py        # API key、命令权限和安全策略
├── telemetry.py       # 事件存储、日志、trace 和观测快照
├── worker.py          # 常驻 worker 和线程池生命周期
└── workspace.py       # `.flow` 工作区布局、初始化和进程锁
```

`infra/workspace.py` 只负责提供通用的工作区路径、目录初始化和进程锁能力；它不是启动流程编排，也不包含具体业务初始化。

### `bootstrap/`：组合根

`bootstrap` 是唯一负责对象装配的地方：

- `config.py` 从项目根目录加载并校验 `config.toml`；
- `container.py` 创建应用运行时和各类依赖；
- `service_app.py` 定义整个进程的 `ServiceApp` 生命周期；
- `main.py` 是 Python 进程入口，直接编排工作区初始化、应用创建和进程生命周期。

## 依赖方向

依赖方向按“外层依赖内层、组合根依赖所有实现”组织：

```text
                         bootstrap
                    组合和启动整个进程
                      │       │       │
          ┌───────────┘       │       └───────────┐
          ▼                   ▼                   ▼
    application          interfaces             infra
      业务用例             外部适配器            通用技术设施
          │                   │
          ▼                   ├──> 应用消息模型
  domain + feature infra      └──> bus / security / workspace
          │
          └──────────────────────────────> infra

    infra ──> Python 标准库和第三方技术库
```

具体约束如下：

- `application.<feature>.domain` 不依赖同一模块的 `app` 或 `infra`。
- `application` 可以依赖自己的 `domain`、自己的 `infra`、应用能力以及顶层共享 `infra`。
- `interfaces` 可以依赖稳定的应用消息模型和顶层 `infra`，不能直接依赖业务私有存储。
- 顶层 `infra` 只能依赖 Python 标准库和第三方技术库，不能反向导入业务层、接口层或启动层。
- `bootstrap` 可以依赖 `application`、`interfaces` 和 `infra`，负责把具体实现连接起来。
- 所有层都不能形成循环依赖；架构测试会检查这些约束。

`application` 内部保持以下单向依赖：

```text
passive ──────┐
proactive ────┤
delegation ───┤──> agent ───> capabilities
schedule ─────┘

automation ───> capabilities + infra
memory ───────> capabilities + infra
```

`agent` 是共享执行内核，不能反向依赖任何业务模块；`capabilities` 只提供通用能力，不能依赖 `passive`、`proactive` 或其他具体业务。应用层导入图由架构测试检查，确保不存在循环依赖。

因此，以下两种 `infra` 含义不同：

```text
application/passive/infra/       # 被动业务专属实现
application/schedule/infra/      # 用户定时任务专属实现
application/automation/infra/    # 自动化作业专属实现
infra/                            # 所有业务共享的技术设施
```

## 进程启动生命周期

从仓库根目录执行 `./scripts/start.sh` 后，启动链路如下：

```text
scripts/start.sh
    ↓ 进入 backend，使用项目运行环境
python -m bootstrap.main
    ↓ 加载 config.toml
ServiceApp.init()
    ↓ 获取工作区进程锁，创建运行时资源
ServiceApp.start()
    ↓ 启动渠道、被动处理、自动化作业、主动线路和消息分发
ServiceApp.wait()
    ↓ 主线程阻塞，等待停止信号
ServiceApp.stop()
    ↓ 逆序停止服务、join 后台线程、释放进程锁
```

`ServiceApp` 只负责进程级生命周期；业务运行时的具体行为仍由 `application` 中的应用服务负责。

运行时用户数据统一保存在仓库根目录的 `.flow/`，路径按根目录的 `config.toml`
解析，与从仓库根目录还是 `backend/` 启动无关。

## 开发

新增代码时遵守以下规则：

- 业务规则放在 `application`，不要塞进顶层 `infra`。
- 顶层 `infra` 提供稳定的技术能力和清晰的模块级说明。
- 新的外部实现通过应用端口、消息类型或适配器接入，不在业务代码中直接创建全局客户端。
- 修改行为时同步补充测试，并保持依赖方向无循环。
- 不考虑旧代码的兼容性，统一以最新为标准

根目录的启动、配置和 Docker 说明见 [`../README.md`](../README.md)。
