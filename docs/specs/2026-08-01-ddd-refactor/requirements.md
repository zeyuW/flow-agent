# DDD 重构第一阶段需求

状态：已确认

版本：2.0

更新日期：2026-08-02

## 1. 阶段目标

第一阶段建立前后端分离的仓库骨架、Python `backend/src` 布局、模块化 DDD 包根和架构门禁，并以单一 TOML、单一 Schema、单一 Loader 的单向配置实现替换现有全局配置系统。

阶段结束时，现有产品行为保持不变，配置静态导入环消失，项目可以安装、启动并通过全量回归。第一阶段不迁移具体业务模块，只建立后续迁移所需的稳定工程边界。

## 2. 范围

- 创建 `backend/`，将 Python 构建配置、锁文件、测试和现有包移动到后端边界。
- 将现有业务包机械移动到 `backend/src/flow_agent`，作为有明确删除期限的迁移期实现。
- 创建 `backend/src/modules`、`backend/src/interfaces`、`backend/src/infra` 和 `backend/src/bootstrap` 包根。
- 调整 Setuptools、Pytest、CLI 和开发命令，使 `backend/src` 成为唯一 Python 包根。
- 在 `backend/src/infra/config` 实现不可变配置模型、纯 TOML Loader 和两阶段 Config Watcher。
- 由 `bootstrap` 组合根加载配置并显式注入运行时，删除全局 Settings Proxy 和模块级配置缓存。
- 让 Agent、LLM Client 和运行单元只接收所需配置切片。
- 删除旧配置包、旧 LLM 配置 Builder 和 `ConfigValues`。
- 新增静态导入图、循环检测和模块化分层架构测试。
- 提供无凭据的 `backend/config.example.toml`，继续忽略本地 `backend/config.toml`。
- 保持根目录文档和工程支撑目录；第一阶段不要求实现前端应用。

## 3. 非目标

- 不在本阶段迁移 Conversation、Proactive、Delegation、Jobs、Scheduling、Memory、Delivery 或 Capabilities 的业务实现。
- 不在本阶段创建没有代码的完整业务目录树。
- 不删除迁移期 `backend/src/flow_agent`；后续按模块迁移完成后再删除。
- 不改变渠道协议、消息格式、数据库结构、插件协议或用户功能。
- 不新增第三方 IM 渠道。
- 不引入依赖注入框架、全局服务定位器或运行时自动扫描容器。

## 4. 功能要求

### 4.1 仓库与 Source Layout

- Python 工程构建文件位于 `backend/`。
- `backend/src` 是安装后唯一 Python 包根。
- 迁移期 `flow_agent` 位于 `backend/src/flow_agent`。
- `modules`、`interfaces`、`infra` 和 `bootstrap` 可以从安装后的环境导入。
- `backend/tests` 是后端测试根目录。
- CLI 命令继续使用现有命令名；第一阶段入口迁移到 `bootstrap.cli:main`。
- 根目录不得出现可直接导入的旧 `flow_agent` 包。

### 4.2 配置加载

- `load_config(path: Path) -> AppConfig` 是唯一配置加载函数。
- 配置只读取传入的 TOML 文件，不读取 YAML、隐式备用路径或模块全局状态。
- TOML 字段直接映射到嵌套 Pydantic 模型，不使用逐字段 Getter 或二次 Builder。
- 未知字段必须拒绝；配置对象必须不可变。
- Python 3.11 及以上使用 `tomllib`；Python 3.10 使用条件依赖 `tomli`。
- 缺少主模型必要字段、启用渠道但缺少凭据，以及主动最小间隔大于最大间隔时必须校验失败。

### 4.3 配置注入

- 进程入口只加载一次启动配置并传给组合根。
- 组合根和工厂函数显式接收配置，不得主动访问全局配置。
- Agent 只接收系统提示词等必要业务值。
- LLM Client 只接收单个模型连接配置。
- Worker、Channel 和其他运行单元只接收自身配置切片。
- 业务模块不得导入 Config Loader 或 Watcher。

### 4.4 热更新

- Watcher 持有当前不可变配置快照。
- Reload 先加载并验证候选配置，再让所有 Applier 执行无副作用 Prepare。
- 所有 Prepare 成功后才能 Commit。
- Prepare 失败时清理候选资源并保持旧快照和旧运行对象。
- 同一失败文件修订不得被无限重复处理；文件再次变化后允许重新尝试。
- Commit 只允许不会失败的赋值或原子引用交换。

### 4.5 架构约束

- 全项目内部静态导入图不得存在循环。
- `modules` 内的 Domain 不得导入 Application、Infra、Interfaces 或 Bootstrap。
- `modules` 内的 Application 不得导入具体 Infra、Interfaces 或 Bootstrap。
- 一个业务模块不得导入另一个模块的 Domain、Infra 或私有 Application 实现。
- `interfaces` 不得直接访问模块仓储或领域内部实现。
- `bootstrap` 是唯一可以同时导入 Interfaces、Modules 和具体 Infra 的组合根。
- 迁移期 `flow_agent` 可以临时依赖 `infra.config`，但不得导入 Interfaces 或 Bootstrap。
- 架构测试必须随默认 Pytest 执行。

## 5. 质量要求

- 所有新增或修改的解释性注释和文档字符串使用中文。
- 不复制外部项目的代码、名称、品牌或兼容逻辑。
- 不删除现有失败测试或降低断言强度。
- 每项实现先写失败测试，再写最小实现。
- 每个任务完成后运行相关测试；阶段完成后运行全量 Pytest、限定到新增模块的 Pyright、Black、来源隔离和空白检查。
- 当前全项目 Pyright 基线为 184 个错误；第一阶段不得增加错误，新增配置与架构模块必须零错误。

## 6. 验收标准

- `backend/src`、`backend/tests` 和四个新包根存在，项目可安装且 CLI 入口可解析。
- 根目录旧 Python 包已移动到 `backend/src/flow_agent`。
- 旧配置目录、`ConfigValues`、LLM 配置 Builder、Settings Proxy 和 Settings Cache 已删除。
- 配置依赖严格为 `config.toml -> loader -> schema -> bootstrap`。
- Config Watcher 的成功提交、Prepare 失败回滚和修订去重测试通过。
- 静态导入图不存在大于一个节点的强连通分量。
- 当前 238 个基线测试经路径调整后全部通过。
- 工作区只包含第一阶段需要的代码、测试、规格和构建配置变更。
