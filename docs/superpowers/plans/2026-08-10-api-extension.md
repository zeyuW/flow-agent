# Extension API Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 编写 `docs/api.md`，让开发者可以选择并完成 Plugin、MCP 或 Skill 的最小扩展接入。

**Architecture:** `docs/api.md` 是单一扩展入口，先比较三条路径，再分别说明最小结构、实际接口、生命周期、安全边界和验证方式；最后更新根 README、后端 README、docs 索引和架构文档的入口。

**Tech Stack:** Markdown、ASCII 流程图、Python Plugin API、JSON/TOML MCP 配置、Skill Markdown 元数据。

## Global Constraints

- 正式文档固定为 `docs/api.md`，并从根 README、backend README、docs README 和架构文档链接进入。
- 文档使用中文，稳定 API 名称、配置字段、目录名和命令保持原样。
- 内容以当前 `Plugin`、MCP Registry、Skill Loader/Registry 和现有示例为准。
- 功能示例解释扩展思路和最小接口，不把文档写成源码路径清单。
- 不写真实密钥、个人数据或运行时日志，不鼓励在导入阶段创建外部连接。
- 明确扩展必须经过配置校验、工具守卫、生命周期管理和运行时快照。

---

### Task 1: 编写扩展路线总览和 Plugin 章节

**Files:**
- Create: `docs/api.md`

**Interfaces:**
- Consumes: 已确认的扩展设计、`Plugin` 基类、插件装饰器、`PluginContext`、示例插件。
- Produces: `docs/api.md` 的路线选择表、Plugin 最小接入、工具/钩子/作业/生命周期说明。

- [ ] **Step 1: 写入路线选择和共同边界**

  用 ASCII 图说明何时选择 Plugin、MCP、Skill；加入三条路径的适用场景、是否需要 Python 和主要产物对比表；明确三者都受配置校验、工具守卫、快照和生命周期约束。

- [ ] **Step 2: 写入 Plugin 最小目录和工具示例**

  使用以下最小示例说明 `Plugin`、`@tool` 和 `PluginContext`：

  ```python
  from application.capabilities.plugins.plugin_base import Plugin
  from application.capabilities.plugins.plugin_decorators import tool

  class ExamplePlugin(Plugin):
      @tool(name="example_echo", description="返回输入文本")
      def echo(self, text: str) -> str:
          return f"收到：{text}"
  ```

  同时说明工具名称、描述、方法签名和 docstring 如何影响模型可见的工具 schema。

- [ ] **Step 3: 写入 Plugin 贡献类型和生命周期**

  说明 `before_turn_modules()`、`before_reasoning_modules()`、`prompt_render_modules()`、`reasoner_modules()`、`after_reasoning_modules()`、`after_turn_modules()`、`turn_started_modules()`、`proactive_sources()`、`proactive_modules()`、`background_jobs()` 和 `mcp_servers()` 的用途；说明 `initialize()` 注入上下文后运行，`shutdown()` 负责资源释放。

- [ ] **Step 4: 写入装饰器和私有状态示例**

  说明 `@on_before_turn`、`@on_after_turn`、`@on_turn_started`、`@on_after_reasoning`、`@on_tool_pre` 和 `@tool`；给出 `self.context.config.get(...)`、`self.context.kv_store.get/set/increment(...)` 的配置与持久化示例，并强调状态必须写入插件私有数据目录。

- [ ] **Step 5: 写入 Plugin 热更新和失败语义**

  用 ASCII 图说明发现、候选准备、原子发布、旧版本保留和停止清理；明确插件加载失败时不替换旧版本，正在执行的回合继续使用既有快照。

### Task 2: 补充 MCP 接入章节

**Files:**
- Modify: `docs/api.md`

**Interfaces:**
- Consumes: `McpServerSpec`、`.flow/mcp.json` 项目配置、`McpServerRegistry` 和 MCP Tool Wrapper 行为。
- Produces: 自定义 MCP Server 的配置示例、工具发现/注册/调用和热更新说明。

- [ ] **Step 1: 写入 MCP 配置最小示例**

  使用以下格式解释项目级外部 MCP：

  ```json
  {
    "schemaVersion": 1,
    "mcpServers": {
      "example": {
        "enabled": true,
        "command": "python",
        "args": ["server.py"],
        "cwd": "./mcp/example",
        "env": {},
        "watchPaths": ["./mcp/example"]
      }
    }
  }
  ```

  解释 `command`、`args`、`cwd`、`env`、`watchPaths`、`enabled` 和 `schemaVersion`，并说明相对路径以 `.flow/mcp.json` 所在项目目录解析。

- [ ] **Step 2: 写入 MCP 运行流程**

  用 ASCII 图说明配置解析、路径校验、Registry 合并、启动握手、工具发现、包装进 Tool Registry、工具守卫和 Agent 调用；区分项目级 MCP、内置 MCP 和插件声明的 MCP。

- [ ] **Step 3: 写入 MCP 失败、安全和热更新语义**

  明确 MCP 名称冲突会拒绝合并；路径和插件工作目录不能越出允许边界；连接失败、工具超时和子进程退出不能把不可用工具暴露给 Agent；候选服务全部准备成功后才替换旧代，失败时保留旧代。

- [ ] **Step 4: 写入 MCP 验证步骤**

  给出开发者可执行的验证顺序：检查 `.flow/mcp.json`、启动服务、查看 MCP/工具状态、调用最小工具、修改 `watchPaths` 后等待热更新、停止服务确认子进程退出；不写真实凭据。

### Task 3: 补充 Skill 接入章节

**Files:**
- Modify: `docs/api.md`

**Interfaces:**
- Consumes: `SkillManifest`、`SkillLoader`、`SkillSpec`、`SkillRegistry` 和 `.flow/skills/README.md` 约定。
- Produces: 自定义 Skill 目录、元数据、匹配约束、资源边界和验证说明。

- [ ] **Step 1: 写入 Skill 最小目录和 SKILL.md 示例**

  使用以下目录结构和元数据说明 Skill：

  ```text
  .flow/skills/example/
  ├── skill.json
  ├── SKILL.md
  ├── scripts/
  ├── references/
  └── assets/
  ```

  `SKILL.md` 示例至少包含 `name:`、`description:`、`requires_tools:`、`requires_sources:`、`requires_mcp:`、`requires_vision_model:` 和 `requires_image_output:` 字段，并说明它们如何参与解析与能力匹配。

- [ ] **Step 2: 写入 skill.json 和资源边界**

  说明 `skill.json` 的 `name`、`description`、`version`、`compatibility`、`enabled` 和 `metadata`；说明 `scripts/`、`references/`、`assets/` 是可选目录，脚本和资源必须留在 Skill 自己的目录边界内。

- [ ] **Step 3: 写入 Skill 与 Plugin/MCP 的选择规则**

  明确 Skill 适合知识、流程和资源；需要 Python 工具、事件钩子、后台作业或主动数据源时选择 Plugin；需要独立外部工具服务时选择 MCP；Skill 不能伪装权限控制、绕过 Tool Registry 或覆盖安全策略。

- [ ] **Step 4: 写入 Skill 加载、匹配和验证流程**

  用 ASCII 图说明扫描、解析、注册、检查 `requires_*` 条件和选中注入；给出最小验证方法：检查 manifest、加载列表、确认依赖能力存在、执行一次匹配任务，并验证非法或缺失元数据不会被静默当作可用能力。

### Task 4: 补充统一生命周期、安全、调试和导航

**Files:**
- Modify: `docs/api.md`
- Modify: `README.md`
- Modify: `backend/README.md`
- Modify: `docs/README.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: 三条扩展章节、现有文档导航和架构扩展层。
- Produces: `docs/api.md` 的统一验证章节，以及四处到 `docs/api.md` 的直接链接。

- [ ] **Step 1: 写入统一生命周期和安全章节**

  说明发现、校验、候选准备、原子发布、运行快照、热更新、失败保留旧版本和停止释放资源；统一强调工具守卫、路径校验、密钥脱敏、私有数据目录和不在导入阶段联网。

- [ ] **Step 2: 写入调试与验证清单**

  分别列出 Plugin、MCP、Skill 的加载、工具可见性、失败回滚、热更新和资源清理验证；给出 `cd backend && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q` 作为项目测试命令，并提醒真实外部服务需要凭据和网络。

- [ ] **Step 3: 更新四处导航**

  在根 README、backend README、docs README 增加“扩展 API”链接；在架构文档扩展层/阅读指引增加 `features/` 与 `api.md` 的关系说明。

- [ ] **Step 4: 执行文档校验**

  运行：

  ```bash
  test -f docs/api.md
  test -f README.md && test -f backend/README.md && test -f docs/README.md && test -f docs/ARCHITECTURE.md
  git diff --check
  rg -n 'docs/api\.md|Plugin|MCP|Skill' docs/api.md README.md backend/README.md docs/README.md docs/ARCHITECTURE.md
  ```

  预期：正式文档存在，四处导航出现，Markdown 无空白错误，三条扩展路径均被提及。

### Task 5: 回归验证和交付检查

**Files:**
- Verify: `docs/api.md`, `README.md`, `backend/README.md`, `docs/README.md`, `docs/ARCHITECTURE.md`

- [ ] **Step 1: 检查所有相对链接目标**

  确认 `docs/api.md`、六篇功能文档、架构文档、后端 README 和配置入口全部存在；外部 HTTPS 链接不参与本地文件检查。

- [ ] **Step 2: 检查占位符和敏感信息**

  运行 `rg -n 'TODO|TBD|待定|sk-[A-Za-z0-9]|bot_token\s*[:=]\s*[A-Za-z0-9]' docs/api.md README.md backend/README.md docs/README.md docs/ARCHITECTURE.md`，只允许示例中的 `replace-me`，不得出现真实凭据或未完成标记。

- [ ] **Step 3: 运行测试并记录环境限制**

  运行：

  ```bash
  cd backend && env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
  ```

  记录通过数量和任何与本次文档无关的既有失败，不修改业务代码。
