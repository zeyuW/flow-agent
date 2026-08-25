# Flow Agent Backend

这是 Flow Agent 的 Python 后端，使用 Python 3.11+ 和 `backend/src` 源码布局。后端负责业务用例、外部渠道适配、共享基础设施和进程启动。

## 目录

```text
backend/
├── pyproject.toml       # Python 版本、依赖和工具配置
├── uv.lock              # 依赖锁定文件
├── src/
│   ├── application/     # 业务模块、应用用例和通用 Agent 能力
│   ├── interfaces/      # 管理 API、HTTP、Telegram、QQ、CLI 等外部适配器
│   ├── infra/           # 配置、消息总线、持久化、worker 和运行保障
│   └── bootstrap/       # 配置加载、依赖装配和 ServiceApp 生命周期
└── tests/               # 单元、集成和架构边界测试
```

### `application/`

业务按语义边界组织：

```text
application/
├── agent/         # 被动、主动和委托共用的 Agent 执行内核
├── passive/       # 接收消息并回复
├── proactive/     # 发现内容并主动推送
├── schedule/      # 用户创建的定时任务
├── automation/    # 系统和插件自动化作业
├── delegation/    # 子 Agent 创建、执行和完成通知
├── memory/        # 记忆检索、写入、去重和整理
└── capabilities/  # LLM、MCP、Skills、Tools、Plugins 和行为策略
```

复杂业务按需拆分为：

```text
application/<feature>/
├── domain/   # 领域模型、状态和规则
├── app/      # 用例编排、端口和事务边界
└── infra/    # 只属于本业务的存储和技术实现
```

`domain` 不依赖技术实现；`app` 组织用例；业务专属 `infra` 不能被其他业务或顶层共享 `infra` 反向依赖。`agent` 和 `capabilities` 是应用层共享能力，不能反向依赖 `passive`、`proactive` 等具体业务。

### `interfaces/`

接口层负责协议转换和渠道生命周期。`interfaces/channels/` 提供统一渠道契约、注册服务以及 CLI、HTTP、Telegram、QQ 适配器。渠道把外部输入转换为统一应用消息，也把统一出站消息转换为平台调用；业务代码不直接创建平台客户端。

`interfaces/admin/` 提供绑定到本机的管理 API。它为 Web 控制台提供会话、追踪、事件、定时任务和能力查询，也提供 MCP 服务、Skill 和定时任务的受控管理操作；它不是公网业务 API。

### `infra/`

顶层 `infra` 只放跨业务共用的技术能力：

```text
infra/
├── bus/          # 入站、出站、事件和可靠投递
├── config.py     # 配置模型、TOML 加载和热更新
├── persistence.py # SQLite 和通用 outbox
├── resilience.py # 重试、错误分类和降级
├── runtime.py    # 运行单元和健康状态
├── security.py   # API key、权限和安全策略
├── telemetry.py  # 日志、trace 和观测
├── worker.py     # worker、线程池和后台执行
└── workspace.py  # `.flow` 工作区和进程锁
```

顶层 `infra` 不依赖 `application`、`interfaces` 或 `bootstrap`；业务专属存储留在对应的 `application/<feature>/infra`。

### `bootstrap/`

`bootstrap` 是组合根，负责加载根目录的 `config.toml`、创建依赖、组装运行时并管理 `ServiceApp` 的 `init()`、`start()`、`wait()` 和 `stop()` 生命周期。它负责连接实现，不承载业务规则。

## 依赖方向

```text
bootstrap
  ├── application
  ├── interfaces ──> 统一应用消息、顶层 infra
  └── infra

application
  ├── 自身 domain / app / infra
  └── 顶层 infra

infra
  └── 标准库和第三方技术库
```

必须保持以下约束：

- `domain` 不依赖 `app`、`infra`、`interfaces` 或 `bootstrap`；
- 顶层 `infra` 不依赖业务层、接口层或启动层；
- `interfaces` 不直接操作业务私有仓储；
- `bootstrap` 可以依赖所有实现，但只负责装配；
- 所有层都不能形成循环依赖。

架构约束位于 `tests/architecture/`，用于防止目录职责和导入方向漂移。

## 配置和运行

从仓库根目录复制配置并填写主模型凭据：

```bash
cp config.example.toml config.toml
./scripts/start.sh
```

`config.toml` 是仓库根目录的唯一 TOML 配置源。相对路径中的 `.flow/` 会解析到用户运行目录 `~/.flow/`；这里保存会话、记忆、日志、追踪、插件、用户 Skill、MCP 配置和子 Agent 任务记录。项目共享 Skill 放在仓库根目录 `skills/`。不要把 `config.toml`、密钥或 `~/.flow/` 运行数据提交到 Git。

后端默认启动本机管理 API：

```text
127.0.0.1:8790/api
```

管理 API 的查询和变更入口见[管理控制台与本机 API](../docs/features/control-plane.md)。前端开发可执行 `./scripts/dev.sh`，只启动后端则使用 `./scripts/start.sh`。

## 验证命令

从仓库根目录执行：

```bash
cd backend && uv run pytest -q
cd backend && uv run black src tests
cd backend && uv run pyright
```

文档改动不改变代码测试范围；真实模型、渠道和外部服务仍需要凭据、网络和对应服务端进行验证。

## 继续阅读

- [文档总索引](../docs/README.md)
- [系统架构](../docs/ARCHITECTURE.md)
- [扩展 API：Plugin、MCP 和 Skill 二次开发](../docs/api.md)
- [管理控制台与本机 API](../docs/features/control-plane.md)
- [Agent Loop](../docs/features/agent-loop.md)
- [被动回复](../docs/features/passive.md)
- [主动回复](../docs/features/proactive.md)
- [后台任务](../docs/features/automation.md)
- [记忆](../docs/features/memory.md)
- [渠道](../docs/features/channels.md)
- [文档维护规则](../docs/knowledge.md)
- [根目录快速开始](../README.md)
- [前端控制台开发说明](../frontend/README.md)
