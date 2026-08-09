# Flow Agent 架构规范

状态：当前生效

版本：4.0

更新日期：2026-08-09

本文是项目当前生效的架构总规范。历史设计文档继续保留用于追溯，但不再作为
新增代码和迁移代码的判断依据。

## 文档目录与生效顺序

- `docs/specs/`：正式架构、功能设计、需求和实施计划，是开发的主要依据。
- `docs/superpowers/`：开发过程记录，用于保存讨论、计划和验证过程，不替代正式规范。
- 根目录 `README.md` 和 `backend/README.md`：快速开始、目录概览和使用说明。

出现冲突时，按以下顺序处理：

1. 用户当前明确提出的要求；
2. 本文件和 `docs/specs/` 中当前生效的规范；
3. 根目录和 `backend/` 下的使用说明；
4. `docs/superpowers/` 中的过程记录；
5. 历史设计和已完成任务文档。

除代码标识符、命令、路径和第三方专有名词外，新增项目文档统一使用中文。

当前重点规范：

- [统一 IM 渠道适配层设计](2026-08-09-unified-channel-adapters/design.md)
- [统一 IM 渠道适配层实施计划](2026-08-09-unified-channel-adapters/tasks.md)

## 一、顶层目录职责

```text
backend/src/
├── application/       # 业务模块、领域模型和应用用例
├── interfaces/        # HTTP、CLI、MCP 和 IM 等外部协议适配
├── infra/             # 所有业务共用的技术基础设施
└── bootstrap/         # 配置装配、进程生命周期和组合根
```

### `application/`：业务实现

业务按语义边界组织，包括 `agent`、`passive`、`proactive`、`schedule`、
`automation`、`delegation`、`memory` 和 `capabilities`。

```text
application/
├── agent/         # Agent 通用执行内核
├── passive/       # 被动接收消息并回复
├── proactive/     # 主动发现内容并推送
├── schedule/      # 用户创建的定时任务
├── automation/    # 系统和插件自动化作业
├── delegation/    # 子 Agent 委派
├── memory/        # 记忆管理
└── capabilities/  # LLM、MCP、Skills、Tools 和 Plugins
```

复杂业务按需拆分为：

```text
application/<feature>/
├── domain/       # 领域对象、规则和领域事实
├── app/          # 用例编排、流程、端口和事务边界
└── infra/        # 仅属于本业务的存储、网关和技术实现
```

业务自己的 `application/<feature>/infra` 属于业务实现，可以被该业务的
`app` 使用；它不能被其他业务模块或顶层共享 `infra` 反向依赖。

### `interfaces/`：外部接入层

接口层负责把外部协议转换为统一的应用消息，并把应用输出转换回平台协议。
它可以依赖稳定的应用消息模型和顶层 `infra`，但不应直接操作业务私有仓储。

其中 `interfaces/channels` 是统一 IM 接入层：

```text
interfaces/channels/
├── base.py       # 渠道协议、能力、上下文、状态和生命周期基类
├── service.py    # 渠道注册、配置构造、启动、停止和 join
├── cli.py        # CLI 适配器
├── http.py       # 通用 HTTP Webhook 适配器
├── telegram.py   # Telegram Bot API 适配器
├── qq.py         # OneBot QQ 适配器
└── qqbot.py      # QQ 官方 Bot WebSocket 适配器
```

新增 IM 时，新增一个适配器文件、在 `service.py` 注册一次工厂，并增加一个
`[channels.<name>]` 配置块。`application`、消息总线和 `ServiceApp` 不得增加
平台特判。

渠道统一使用 `session_id`、`chat_id`、`sender_id` 和 `recipient_id`。平台专属
字段只能留在适配器内部或扩展元数据中，不能作为应用层路由依据。

### `infra/`：共享技术基础设施

顶层 `infra` 只放多个业务共同使用的技术能力：

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

业务专属实现必须留在对应业务的 `application/<feature>/infra`，不能因为使用
SQLite、线程或 HTTP 就移动到顶层 `infra`。

### `bootstrap/`：组合根

`bootstrap` 是唯一负责对象装配和进程生命周期的地方：

- `config.py` 加载项目根目录的 `config.toml`；
- `container.py` 创建应用运行时和业务依赖；
- `service_app.py` 管理进程级 `init()`、`start()`、`wait()` 和 `stop()`；
- `main.py` 创建 `ServiceApp` 并处理进程入口。

## 二、依赖方向

```text
bootstrap
  ├── application
  ├── interfaces ──> application 消息模型、infra
  └── infra

application
  ├── 自身 domain / app / infra
  └── 顶层 infra

infra
  └── 标准库和第三方技术库
```

约束如下：

- `domain` 不依赖 `app`、`interfaces`、顶层 `infra` 或 `bootstrap`；
- `application` 可以依赖自己的 `domain`、自己的 `infra` 和顶层共享 `infra`；
- `interfaces` 可以依赖应用消息模型和顶层 `infra`，不能依赖业务私有存储；
- 顶层 `infra` 不得依赖 `application`、`interfaces` 或 `bootstrap`；
- `bootstrap` 可以依赖所有实现层，但只负责装配，不承载业务规则；
- 所有层都不能形成循环依赖。

因此需要区分：

```text
application/passive/infra/      # 被动业务专属实现
application/schedule/infra/     # 用户定时任务专属实现
application/automation/infra/   # 系统和插件自动化作业实现
infra/                          # 所有业务共用的技术能力
```

## 三、渠道配置和生命周期

渠道采用配置驱动注册：

```toml
[channels.telegram]
enabled = true
bot_token = "..."
allowed_users = ["..."]
allowed_groups = []

[channels.qq]
enabled = false
host = "127.0.0.1"
port = 8789
api_base = "http://127.0.0.1:5700"
```

`ChannelService` 负责按配置构造渠道，并统一调用：

```python
channel_service.start_all()
channel_service.stop_all()
channel_service.join_all(timeout=8.0)
```

适配器内部可以使用线程、asyncio、HTTP 服务或 WebSocket，但这些细节不能泄漏
到 `ServiceApp` 或业务层。

进程停止顺序是：停止渠道入口、停止业务运行时、停止消息分发、join 渠道和后台
线程、释放进程锁。

## 四、业务消息和消息总线

`infra.bus` 是进程内唯一消息总线。入站消息经过渠道规范化后进入总线，出站消息
通过统一 `ChannelDeliveryResult` 返回投递结果，可靠重试由消息总线负责。

对话管道使用 `TurnFlow.chat_id` 构造被动回复、错误回复、流式事件和主动工具
调用目标。主动消息、定时消息和委托完成消息也只使用通用渠道地址。

## 五、开发规则

- 新业务规则放在 `application`，不要塞入顶层 `infra`；
- 新外部平台通过接口适配器和 `ChannelService` 接入；
- 不在业务代码中直接创建第三方客户端；
- 行为变更必须补充测试，并验证依赖方向；
- 不恢复已删除的旧导入路径或兼容转发层；
- 修改后至少运行架构测试和全量测试。

后端测试命令：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```
