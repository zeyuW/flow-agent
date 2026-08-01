# DDD 重构第一阶段需求

状态：已确认

日期：2026-08-01

## 1. 阶段目标

第一阶段建立标准 `src/` 布局和四层包骨架，并把现有配置系统替换为单一 TOML、单一 Schema、单一 Loader 的单向实现。阶段结束时现有产品行为保持不变，配置静态导入环消失，项目仍可启动且全量测试通过。

## 2. 范围

- 将现有 `flow_agent` 包机械移动到 `src/flow_agent`，不在本阶段改写其业务模块边界。
- 创建 `src/domain`、`src/application`、`src/infra`、`src/interfaces` 四层包骨架。
- 调整 Setuptools、Pytest 和 CLI 构建配置，使 `src` 成为唯一 Python 包根。
- 在 `src/infra/config` 实现不可变 Pydantic 配置模型、纯 TOML Loader 和两阶段 Config Watcher。
- 让 `interfaces` 组合根显式加载并传递 `AppConfig`，删除全局 Settings Proxy 和模块级配置缓存。
- 让 Agent 和 LLM Client 只接收所需配置切片，不再依赖完整配置对象。
- 删除旧 `flow_agent/config`、旧 `flow_agent/llm/config.py` 和 `ConfigValues`。
- 新增静态导入图、循环检测和四层依赖架构测试。
- 提供无凭据的 `config.example.toml`，继续忽略本地 `config.toml`。

## 3. 非目标

- 本阶段不迁移 Conversation、Proactive、Delegation、Jobs、Scheduling、Memory、Delivery 或 Capabilities 的业务实现。
- 本阶段不删除临时存在于 `src/flow_agent` 的旧业务包；它在后续阶段按上下文迁移后删除。
- 本阶段不改变渠道协议、数据库结构、消息格式、插件协议或用户功能。
- 本阶段不引入依赖注入框架或全局服务定位器。

## 4. 功能要求

### 4.1 Source Layout

- `src` 是 Setuptools 和测试运行时唯一包根。
- `flow_agent` 暂时位于 `src/flow_agent`。
- `domain`、`application`、`infra`、`interfaces` 均可从安装后的环境导入。
- CLI 命令继续使用现有 `flow-agent` 名称；第一阶段入口仍可指向 `flow_agent.main:main`。

### 4.2 配置加载

- `load_config(path: Path) -> AppConfig` 是唯一配置加载函数。
- 配置只读取传入的 TOML 文件，不读取环境变量、YAML 或隐式备用路径。
- TOML 字段直接映射到嵌套 Pydantic 模型，不使用逐字段 Getter 或二次 Builder。
- 未知字段必须拒绝；配置对象必须不可变。
- Python 3.11 及以上使用 `tomllib`；Python 3.10 使用条件依赖 `tomli`。
- 缺少主模型 API Key、启用 Telegram 但缺少令牌/允许用户、启用主动推送但缺少目标用户，以及主动最小间隔大于最大间隔时必须校验失败。

### 4.3 配置注入

- `main` 只加载一次启动配置并传给组合根。
- 组合根和工厂函数显式接收 `AppConfig`，不得主动访问全局配置。
- Agent 只接收系统提示词等所需值。
- OpenAI LLM Client 只接收单个模型连接配置。
- 运行单元只接收自身需要的配置切片。

### 4.4 热更新

- Watcher 持有当前不可变配置快照。
- Reload 先加载并验证候选配置，再让所有 Applier 执行无副作用 Prepare。
- 所有 Prepare 成功后才能 Commit。
- Prepare 失败时清理已准备资源并保持旧快照与旧运行对象。
- 同一失败文件修订不得被无限重复处理；文件再次变化后允许重新尝试。

### 4.5 架构约束

- 全项目内部静态导入图不得存在环。
- `domain` 不得导入其他三层。
- `application` 不得导入 `infra` 或 `interfaces`。
- 除 `interfaces.bootstrap` 外，`interfaces` 不得直接导入 Infra 具体实现。
- 架构测试必须在 CI 中随 Pytest 执行。

## 5. 质量要求

- 所有新增或修改的解释性注释和文档字符串使用中文。
- 不复制外部项目的代码、命名、品牌或兼容逻辑。
- 不删除现有失败测试或降低断言强度。
- 每项实现先写失败测试，再写最小实现。
- 每个任务完成后运行相关测试；阶段完成后运行全量 Pytest、限定到新增/修改模块的 Pyright、带 `--target-version py310 --fast` 的 Black、来源隔离和空白检查。
- 当前全项目 Pyright 基线为 184 个错误；第一阶段不得增加错误，并要求新增 `infra.config` 与架构测试模块零错误。全项目类型债务在后续业务迁移阶段随模块迁移逐步清零。

## 6. 验收标准

- `src` 布局和四层包骨架存在，项目安装和 CLI 入口可解析。
- 旧配置目录、`ConfigValues`、`llm/config.py`、`_SettingsProxy` 和 Settings Cache 已删除。
- 配置依赖严格为 `config.toml -> loader -> schema -> bootstrap`。
- Config Watcher 的成功提交和 Prepare 失败回滚测试通过。
- 静态导入图无强连通分量大于 1 的循环。
- 当前 238 个基线测试经必要导入调整后全部通过。
- 工作区只包含第一阶段需要的代码、测试、规格和构建配置变更。
