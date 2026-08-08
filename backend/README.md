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

业务按边界组织，目前包括 `conversation`、`memory`、`proactive`、`tasks`、`scheduling`、`delegation` 和 `capabilities`。

复杂业务模块通常按以下职责划分：

```text
application/<feature>/
├── domain/      # 领域模型、状态、规则和领域事实
├── app/         # 用例编排、流程、事务边界和失败策略
└── infra/       # 仅属于该业务的存储和外部技术实现
```

`domain` 不读取配置、不操作数据库、不访问网络，也不依赖具体 SDK。`app` 负责把领域对象、应用能力和业务基础设施组织成完整用例。`application/<feature>/infra` 可以依赖本业务的 `domain`，用于实现业务专属的仓储、网关或持久化逻辑。

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

业务专属实现必须留在 `application/<feature>/infra`；例如任务存储、会话存储和主动线路状态存储都带有业务语义，不能因为使用 SQLite 就移动到顶层 `infra`。

### `bootstrap/`：组合根

`bootstrap` 是唯一负责对象装配的地方：

- `config.py` 从项目根目录加载并校验 `config.toml`；
- `container.py` 创建应用运行时和各类依赖；
- `service_app.py` 定义整个进程的 `ServiceApp` 生命周期；
- `main.py` 是 Python 进程入口；
- `workspace.py` 编排启动阶段的工作区初始化。

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

因此，以下两种 `infra` 含义不同：

```text
application/conversation/infra/   # 会话业务专属实现
application/tasks/infra/          # 任务业务专属实现
infra/                             # 所有业务共享的技术设施
```

## 进程启动生命周期

从仓库根目录执行 `./scripts/start.sh` 后，启动链路如下：

```text
scripts/start.sh
    ↓ 进入 backend，清理 ROS/PYTHONPATH 环境
python -m bootstrap.main
    ↓ 加载 config.toml
ServiceApp.init()
    ↓ 获取工作区进程锁，创建运行时资源
ServiceApp.start()
    ↓ 启动渠道、ChatWorker、后台任务、主动线路和消息分发
ServiceApp.wait()
    ↓ 主线程阻塞，等待停止信号
ServiceApp.stop()
    ↓ 逆序停止服务、join 后台线程、释放进程锁
```

`ServiceApp` 只负责进程级生命周期；业务运行时的具体行为仍由 `application` 中的应用服务负责。

## 开发和测试

在 `backend` 目录运行全量测试：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/architecture tests/infrastructure
```

新增代码时遵守以下规则：

- 业务规则放在 `application`，不要塞进顶层 `infra`。
- 顶层 `infra` 提供稳定的技术能力和清晰的模块级说明。
- 新的外部实现通过应用端口、消息类型或适配器接入，不在业务代码中直接创建全局客户端。
- 修改行为时同步补充测试，并保持依赖方向无循环。
- 不恢复已删除的旧导入路径或兼容包；新代码使用当前聚合模块，例如：

```python
from infra.config import AppConfig
from infra.persistence import SQLiteDatabase
from infra.resilience import RetryPolicy
from infra.bus.types import SendMessage
```

根目录的启动、配置和 Docker 说明见 [`../README.md`](../README.md)。