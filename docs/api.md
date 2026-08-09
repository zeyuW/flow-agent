# Flow Agent 扩展 API

本文是 Flow Agent 的二次开发入口。它回答一个问题：当你需要给系统增加能力时，应该把能力放到 Plugin、MCP 还是 Skill 中，以及如何让它被发现、调用、热更新和验证。

## 先选择扩展路径

三条路径解决的问题不同：

```text
需要增加什么？
      |
      +-- 改变 Agent 的生命周期、事件、工具或后台任务？ --> Plugin
      |
      +-- 接入一个独立进程或外部工具服务？ -------------> MCP
      |
      +-- 提供可复用的知识、步骤、资源或任务说明？ ------> Skill
```


| 路径     | 适合增加                          | 是否拥有生命周期              | 是否直接提供工具       |
| ------ | ----------------------------- | --------------------- | -------------- |
| Plugin | 事件钩子、Agent 工具、主动模块、后台任务、配置和状态 | 是                     | 是，可注册本地工具      |
| MCP    | 独立服务提供的工具和资源                  | 由 MCP 服务负责，Agent 管理连接 | 是              |
| Skill  | 指令、知识、脚本、参考资料和资产              | 否                     | 不直接注册 Agent 工具 |


经验法则：需要参与一次对话的执行过程时选 Plugin；需要把能力隔离到独立服务时选 MCP；需要让 Agent 掌握一套可复用的方法时选 Skill。一个完整功能也可以组合三者：Skill 描述方法，MCP 提供外部能力，Plugin 负责编排生命周期。

## 共同约束

- 扩展必须有稳定名称和版本，名称用于注册、日志、配置和问题定位。
- 扩展不得绕过统一的工具注册、事件总线和权限检查；需要外部副作用时，先确认调用边界。
- 用户配置和运行状态写入 `.flow/` 下的数据目录，不把密钥、数据库、日志或个人数据提交到仓库。
- 初始化失败应可定位、可重试，并且不能破坏已经运行的旧版本。
- 扩展只依赖公开协议和上下文对象，不依赖 Agent 内部实现细节。

---



## 1. Plugin：扩展 Agent 的运行时行为

Plugin 是最完整的扩展方式。它可以订阅 Agent 生命周期，在模型推理前后介入，注册本地工具，提供主动回复模块和后台任务，并拥有独立配置与持久化键值状态。

### 1.1 插件目录

工作区插件位于 `.flow/plugins/<name>/`。一个可安装、可管理的插件至少应包含 `plugin.py` 和 `plugin.json`：

```text
.flow/plugins/hello_plugin/
├── plugin.json          # 插件身份、版本和启用状态
├── plugin.py            # Plugin 子类及扩展实现
├── _conf_schema.json    # 可选：配置默认值
└── README.md            # 可选：给维护者的说明

.flow/plugin-data/hello_plugin/
├── plugin_config.json   # 运行时配置
└── .kv.json             # PluginKVStore 状态，不应提交
```

插件数据目录由运行时注入。插件不要把可变状态写回插件代码目录，也不要直接操作全局配置文件。

`plugin.json` 示例：

```json
{
  "name": "hello_plugin",
  "description": "为 Agent 增加问候工具",
  "version": "1.0.0",
  "compatibility": ">=1.0.0",
  "enabled": true,
  "metadata": {
    "author": "your-name"
  }
}
```



### 1.2 最小插件

```python
from application.capabilities.plugins.plugin_base import Plugin
from application.capabilities.plugins.plugin_decorators import tool


class HelloPlugin(Plugin):
    """一个只提供本地工具的插件。"""

    @tool(
        name="hello",
        description="向指定用户打招呼",
    )
    async def hello(self, name: str) -> str:
        """参数 name 是需要被问候的名字。"""
        return f"你好，{name}！"
```

`@tool` 会把方法注册为模型可调用的工具。参数类型、方法签名和文档字符串用于生成工具输入说明；需要复杂输入时，应使用明确的类型和校验逻辑，不要把一个无结构的字符串当作所有参数。

### 1.3 生命周期与扩展点

Plugin 的生命周期可以理解为下面的事件流：

```text
加载插件
   |
   +--> initialize()
   |
一轮对话开始 --> turn_started_modules()
   |
   +--> before_turn_modules()       # 可拦截，失败可终止本轮
   +--> before_reasoning_modules()
   +--> reasoner_modules()
   +--> after_reasoning_modules()
   +--> after_turn_modules()        # 观察和记录，不改变已完成结果
   |
后台调度 --> background_jobs()
主动调度 --> proactive_sources() / proactive_modules()
   |
卸载插件 --> shutdown()
```

可用扩展点：

- `turn_started_modules()`：在一轮对话建立上下文时执行。
- `before_turn_modules()`：在本轮正式处理前执行，可作为 Gate 拦截请求。
- `before_reasoning_modules()`、`reasoner_modules()`、`after_reasoning_modules()`：参与推理前准备、推理和推理结果处理。
- `after_turn_modules()`：记录、清理或异步观察本轮结果；不要假设它可以回写已经发送的消息。
- `proactive_sources()`、`proactive_modules()`：向主动回复系统提供候选来源和主动模块。
- `background_jobs()`：声明定时、事件触发或可重试的后台任务。
- `mcp_servers()`：由插件附带声明 MCP 服务，适合插件与外部工具服务一起分发。



### 1.4 钩子：拦截与观察

Plugin 有两种不同的介入方式：阶段模块可以读写 `TurnFlow`，工具前钩子可以阻止或修改工具参数；生命周期装饰器则是 EventBus 通知，适合观察和记录，不直接改变回合结果。示例：

```python
from application.capabilities.plugins.plugin_base import Plugin
from application.capabilities.plugins.plugin_decorators import (
    on_after_turn,
    on_before_turn,
    on_tool_pre,
)
from application.capabilities.plugins.tool_hooks import HookOutcome


class GuardPlugin(Plugin):
    @on_before_turn(priority=10)
    async def record_turn_start(self, ctx):
        self.context.kv_store.set("last_session", ctx.session_id)
        return None

    @on_tool_pre(tool_name="send_message")
    async def check_outbound_message(self, context):
        # 这里可以做收件人、内容和权限检查。
        return None

    @on_after_turn()
    async def record_turn(self, context):
        # 这里适合埋点、审计或更新插件自己的状态。
        return None
```

常用装饰器：

- `@on_before_turn`：收到 `before_turn` 事件时通知插件；需要修改 `TurnFlow` 时使用 `before_turn_modules()`。
- `@on_tool_pre(tool_name=...)`：工具执行前 Gate，可按工具名过滤。
- `@on_after_turn`：本轮结束后的 Tap。
- `@on_turn_started`：本轮开始时执行。
- `@on_after_reasoning`：推理完成后的处理点。

生命周期处理器接收事件上下文 `ctx`，工具前钩子接收包含 `tool_name`、`arguments` 和 `session_key` 的工具上下文。钩子应保持短小、可重入、可失败恢复。耗时工作放入后台任务；需要修改工具参数或阻断危险操作时，必须在工具执行前完成检查。

### 1.5 使用上下文、配置和状态

插件初始化后可以使用运行时注入的 `PluginContext`：

```python
class CounterPlugin(Plugin):
    async def initialize(self):
        self.limit = int(self.context.config.get("limit", 10))
        self.context.kv_store.set("initialized", True)

    async def shutdown(self):
        # 释放自己创建的连接、任务和临时资源。
        return None
```

上下文中最常用的能力是：

- `event_bus`：发布或订阅系统事件。
- `tool_registry`：查看或使用统一工具注册表。
- `config`：读取插件配置。
- `kv_store`：以键值形式保存插件状态，写入过程具备临时文件替换保护。
- `workspace`、`data_dir`：访问工作区信息和插件专属数据目录。

配置默认值可放在插件目录的 `_conf_schema.json`，用户覆盖配置放入插件数据目录的 `plugin_config.json` 或 `config.local.toml`。敏感配置通过本地运行环境提供，不要写进示例文件。

### 1.6 后台任务

通过 `background_jobs()` 返回 `JobSpec`：

```python
from application.automation.domain import JobSpec


class CleanupPlugin(Plugin):
    async def cleanup(self, context):
        # 只处理插件自己的数据，并保持幂等。
        return None

    def background_jobs(self):
        return [
            JobSpec(
                name="cleanup",
                func=self.cleanup,
                interval_seconds=3600,
                max_retries=2,
                retry_delay_seconds=5,
                retry_backoff_factor=2.0,
            )
        ]
```

`JobSpec` 支持按间隔执行，也可以通过 `event_type` 绑定事件，并使用 `debounce_seconds`、`coalesce` 合并重复触发。任务函数应满足：

1. 重复执行不会造成重复副作用。
2. 失败抛出可诊断异常，不吞掉错误。
3. 不依赖进程内未持久化的临时状态。
4. 停止时可以及时取消或退出。



### 1.7 插件加载、热更新和边界

```text
扫描 plugin.py / plugin.json
          |
          v
注入 PluginContext
          |
          v
initialize() ---- 注册工具 / 钩子 / 任务 / MCP 声明
          |
          v
运行时使用
          |
文件变化 --> 停止旧实例 --> 重新加载 --> 初始化新实例
```

热更新不应依赖旧实例继续工作。`shutdown()` 必须释放连接、取消任务并停止自建线程；新版本初始化失败时，应保留可用的旧运行代际，避免一次错误配置导致整套服务不可用。

Plugin 适合编排 Flow Agent 内部行为，但不应：

- 直接修改 Agent 核心循环或绕过统一消息发送接口。
- 直接写其他插件的数据目录。
- 在导入模块时启动永久线程、网络连接或不可取消的任务。
- 把用户输入拼接成未经校验的 shell 命令。

---



## 2. MCP：接入独立工具服务

MCP 适合把外部能力隔离成独立进程，例如浏览器、数据库、企业 API 或本地自动化服务。Flow Agent 负责启动、发现、注册和停止 MCP 服务，把服务暴露的工具接入统一 Tool Registry；工具的具体业务逻辑仍由 MCP 服务负责。

### 2.1 配置一个 MCP 服务

项目级 MCP 配置放在 `.flow/mcp.json`：

```json
{
  "schemaVersion": 1,
  "mcpServers": {
    "weather": {
      "enabled": true,
      "command": "python",
      "args": ["server.py"],
      "cwd": "./mcp/weather",
      "env": {
        "WEATHER_API_BASE": "https://example.invalid"
      },
      "watchPaths": ["./mcp/weather"]
    }
  }
}
```

字段含义：

- `schemaVersion`：配置格式版本，当前使用 `1`。
- `mcpServers`：以服务名为键的服务定义；名称必须唯一。
- `enabled`：设为 `false` 时跳过该服务。
- `command`、`args`：启动命令及参数；运行时会组合成命令参数元组。
- `cwd`：服务工作目录，相对路径相对于 `.flow/mcp.json` 所在目录解析。
- `env`：传给子进程的字符串环境变量。
- `watchPaths`：触发配置重载的文件或目录，相对路径同样相对于 `.flow/mcp.json` 所在目录解析。

不要把 API key 写进 `mcp.json`。在本地配置或进程环境中注入，并在日志中隐藏环境变量值。

### 2.2 MCP 的运行链路

```text
.flow/mcp.json
      |
      v
McpServerRegistry
      |
      +--> 启动 stdio MCP 进程
      +--> 握手并发现工具
      +--> 为工具生成统一 wrapper
      |
      v
Tool Registry
      |
      v
Agent 选择工具 --> wrapper --> MCP 服务 --> 外部系统
```

MCP 服务必须遵循当前运行时支持的 MCP stdio 协议，并提供稳定的工具名称、输入 schema 和错误信息。开发者不需要修改 Agent 主循环来接入新工具；只要服务可以被独立启动并完成协议握手，工具就能进入统一工具调用链。

### 2.3 进程内、项目级和插件附带的服务

MCP 服务来源可以是：

- 内置服务：由应用启动时提供，适合系统必需的能力。
- 项目级服务：写入 `.flow/mcp.json`，适合部署环境或项目使用的外部工具。
- 插件附带服务：在 Plugin 的 `mcp_servers()` 中返回 `McpServerSpec`，适合把插件代码和它依赖的工具服务一起分发。

```python
from application.capabilities.mcp.config import McpServerSpec
from application.capabilities.plugins.plugin_base import Plugin


class ResearchPlugin(Plugin):
    @classmethod
    def mcp_servers(cls):
        return [
            McpServerSpec(
                name="research_db",
                command=("python", "server.py"),
                cwd="./mcp/research_db",
                watch_paths=("./mcp/research_db",),
                source="plugin",
            )
        ]
```

插件声明中的相对路径必须位于插件目录内，运行时会为插件提供专属数据目录环境变量。若服务需要访问工作区之外的路径，应改为显式配置并经过部署环境审查。

### 2.4 自定义 MCP 服务的接入步骤

1. 先单独运行 MCP 服务，确认它可以启动、完成握手并列出工具。
2. 为每个工具定义稳定名称、输入 schema、超时行为和用户可理解的错误。
3. 将启动命令写入 `.flow/mcp.json`，先使用 `enabled: true` 接入一个服务。
4. 重启或等待 watcher 重载，检查服务列表和工具列表。
5. 用一条无副作用的测试请求调用工具，确认参数校验、日志和失败行为。
6. 再接入真实凭据或生产系统，并为危险操作增加服务端权限控制。



### 2.5 重载、失败和停止

```text
检测到配置/代码变化
          |
          v
构造候选服务代际并预热
          |
     +----+----+
     |         |
   成功       失败
     |         |
替换工具表   停止候选，保留旧代际
     |
停止旧服务
```

重载是代际切换，而不是在原进程上随意修改状态：所有候选服务预热成功后才替换工具注册表；任一服务启动或握手失败时，候选服务会被清理，当前可用代际继续提供服务。调用失败应返回可诊断错误，不应静默伪造成功结果。

### 2.6 MCP 安全边界

- `command`、`args`、`cwd` 和 `watchPaths` 属于部署配置，不能由普通用户消息直接生成。
- 启动命令使用结构化参数，不要把整条命令拼成 shell 字符串。
- MCP 服务运行在独立进程中，默认只授予完成任务所需的环境变量、目录和网络权限。
- 对发送消息、写文件、执行命令、修改数据等工具，在 MCP 服务端再次做身份、参数和权限检查。
- 工具返回值需要限制大小并保留错误上下文，避免把密钥、完整环境变量或内部堆栈回传给模型。
- 服务退出、协议异常和工具超时都要可观测；停止时必须回收子进程和连接。

---



## 3. Skill：提供可复用的方法和知识

Skill 是给 Agent 使用的“方法包”，核心是可读的 `SKILL.md`，可以附带脚本、参考资料和资产。它描述如何完成一类任务，不负责拥有 Agent 生命周期，也不应该把外部系统凭据硬编码进文档。

### 3.1 Skill 目录

普通工作区 Skill 放在 `.flow/skills/<name>/`：

```text
.flow/skills/release_note/
├── skill.json             # 管理元数据
├── SKILL.md               # 使用说明和匹配元数据
├── scripts/               # 可选：由支持该 Skill 的运行时受控调用
├── references/            # 可选：规范、模板和背景资料
└── assets/                # 可选：图片、样例或其他资源
```

`skill.json` 示例：

```json
{
  "name": "release_note",
  "description": "根据变更记录生成简洁的发布说明",
  "version": "1.0.0",
  "compatibility": ">=1.0.0",
  "enabled": true,
  "metadata": {
    "category": "writing"
  }
}
```

`SKILL.md` 开头可提供运行时用于筛选的元数据：

```markdown
name: release_note
description: 根据变更记录生成简洁的发布说明
requires_tools: git_log, read_file
requires_sources: workspace
requires_mcp:
requires_vision_model: false
requires_image_output: false

# 发布说明生成

先读取变更记录，再按用户指定的受众组织内容……
```

两份元数据承担不同职责：`skill.json` 用于发现、安装、启用、禁用和版本管理；`SKILL.md` 用于描述具体方法，并声明选择该 Skill 所需要的工具、来源或 MCP 服务。名称和版本应保持一致，发生冲突时先修复元数据，不要依赖目录名猜测身份。

### 3.2 Skill 如何被选择

```text
扫描 SKILL.md / skill.json
          |
          v
SkillLoader 解析名称、描述和依赖
          |
          v
SkillRegistry 对照当前工具、来源、MCP
          |
          +--> 条件满足 --> 返回候选 Skill
          |
          +--> 条件不满足 --> 不选择，记录缺失条件
```

当前 Skill 选择会检查：

- `requires_tools`：工具是否已经注册。
- `requires_sources`：所需数据来源是否可用。
- `requires_mcp`：所需 MCP 服务是否已连接。
- `requires_vision_model`：是否需要视觉模型。
- `requires_image_output`：是否需要图像输出能力。

Skill loader 本身只负责扫描和解析，不会自动执行任意 `scripts/` 文件。普通 Skill 由支持它的运行时读取并注入相应上下文；Drift 场景则由 Drift pipeline 在受控条件下筛选、执行和记录状态。要改变每一轮 Agent 行为或直接注册工具，应使用 Plugin；要提供独立工具服务，应使用 MCP。

### 3.3 如何编写可用的 Skill

一份好的 `SKILL.md` 应当让另一个开发者在没有口头解释的情况下完成任务：

1. 说明适用场景和不适用场景。
2. 明确输入、输出和成功标准。
3. 用有顺序的步骤描述决策过程。
4. 指出需要调用的工具、来源和 MCP 服务。
5. 为失败、缺少数据、权限不足和重复执行写出处理方式。
6. 把长篇背景资料放在 `references/`，正文保持可快速读取。

建议使用这样的任务流程图：

```text
收集输入 --> 检查前置条件 --> 执行步骤 --> 验证结果 --> 输出/记录
    |             |              |            |
    +-- 不完整 --+              +-- 失败 ----+
          返回需要补充的信息       保留原因并安全退出
```

Skill 中的脚本不是权限边界。脚本需要读写文件、访问网络或修改外部系统时，必须通过受控工具或 MCP 服务执行，并由调用链完成权限检查、超时控制和结果审计。

### 3.4 自定义 Skill 的接入步骤

1. 创建唯一目录名，并同时写入 `skill.json` 和 `SKILL.md`。
2. 在 `SKILL.md` 中声明真实依赖，不要为了提高命中率省略 `requires_*` 字段。
3. 将参考资料和资产放入对应子目录，避免在正文中写机器相关的绝对路径。
4. 若需要工具，先确认工具来自现有 Plugin 或 MCP，再编写调用步骤。
5. 启用 Skill 后，用一个满足条件的最小输入验证选择结果。
6. 分别测试缺少工具、缺少 MCP、输入不完整和执行失败时的结果。



### 3.5 Skill 的边界

Skill 不应：

- 伪装成工具声明，或在 Markdown 中要求运行时绕过权限。
- 保存 token、密码、个人数据或长期状态。
- 假设某个工具永远存在；依赖应通过 `requires_*` 声明。
- 通过文档约定偷偷改变其他 Skill、Plugin 或用户配置。
- 将不可逆的外部操作写成默认步骤而不要求确认。

---



## 4. 统一生命周期、安全和验证



### 4.1 三条路径如何组合

```text
Skill: 说明“应该如何做”
          |
          v
Plugin: 决定“何时做、如何编排、如何审计”
          |
          v
MCP: 执行“需要隔离或外部系统完成的动作”
          |
          v
统一 Tool Registry / EventBus / MessageBus
          |
          v
用户可见结果 + 日志 + 可恢复状态
```

例如“定期整理项目进展”可以这样拆分：Skill 描述整理规则和输出格式；MCP 提供项目管理系统查询工具；Plugin 通过 `background_jobs()` 定时触发，通过工具前钩子检查权限，最后将结果交给消息渠道发送。

### 4.2 扩展安全检查清单

- [ ] 名称、版本、兼容性和启用状态已声明。
- [ ] 所有外部输入都经过长度、类型、路径和权限校验。
- [ ] 工具副作用有明确的确认和失败策略。
- [ ] 子进程、网络连接、文件句柄和后台任务可以停止。
- [ ] 用户配置、密钥和运行状态未写入代码、文档或 Git。
- [ ] 重复加载、重复事件和重复任务不会产生重复副作用。
- [ ] 错误日志包含扩展名、操作和原因，但不泄露凭据和个人数据。



### 4.3 验证扩展是否接入成功

建议按以下层次验证：

```text
静态检查 --> 单元测试 --> 最小运行验证 --> 失败/重载验证 --> 真实场景
```

最低验证内容：

- Plugin：插件能加载，工具或钩子出现在注册表，`initialize()` 和 `shutdown()` 都可完成。
- MCP：服务能握手，工具能列出，正常调用和服务异常都能返回明确结果。
- Skill：Skill 能被扫描，依赖满足时能选中，缺少依赖时不会误选。
- 三者组合：重启、重复加载和配置变化后，旧状态没有被破坏。

代码修改后，从仓库根目录运行：

```bash
cd backend && uv run pytest -q
cd backend && uv run pyright
```

只修改文档时，至少检查 Markdown 链接、JSON 示例和空白格式：

```bash
git diff --check
```



## 5. 扩展决策清单

提交二次开发前，先回答：

1. 这个能力是否必须介入 Agent 生命周期？是则优先 Plugin。
2. 这个能力是否需要独立进程、不同依赖或外部系统？是则优先 MCP。
3. 这个能力是否主要是方法、知识或资源？是则优先 Skill。
4. 是否需要三者组合？分别明确“描述、编排、执行”的边界。
5. 失败后系统是否还能继续运行？是否保留旧配置或旧代际？
6. 能否用最小测试证明加载、调用、停止和重载都符合预期？

相关设计文档：

- [系统架构](ARCHITECTURE.md)
- [主动回复](features/proactive.md)
- [后台自动化](features/automation.md)
- [Agent 主循环](features/agent-loop.md)
- [文档总览](README.md)
