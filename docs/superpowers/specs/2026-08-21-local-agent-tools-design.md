# 本地 Agent 原子工具设计

## 目标

为运行在用户本机的 Flow Agent 提供四个可组合的底层 Tool：`read`、`write`、`edit`、`bash`。用户可以从任意已接入的 IM 指挥 Agent 完成本机文件操作和命令执行；Skill、MCP 与 Plugin 在这些原子能力之上组合工作流。

本设计学习 Pi Coding Agent 的四个默认工具语义，但沿用 Flow Agent 的 Python `ToolRegistry`、工具调用链和生命周期。

## 范围

本次只打通主 Agent 的本地执行链路：工具实现、注册、模型调用和测试。

本次不实现 IM 身份授权、二次确认、危险命令拦截、技能市场、自然语言安装 UI、沙箱或跨平台 Shell 适配。这些会在链路可用后独立增加，不能改变四个 Tool 的公开名称和输入契约。

Drift 管线的内部 `read_file`、`write_file` 不在本次改造范围；它不是主 Agent 的 `ToolRegistry` 工具集合。

## 文件组织

```text
backend/src/application/capabilities/tools/
├── read.py       # ReadTool，注册名 read
├── write.py      # WriteTool，注册名 write
├── edit.py       # EditTool，注册名 edit
├── bash.py       # BashTool，注册名 bash
├── base.py       # 已有 Tool / ToolResult 协议
├── registry.py   # 已有 ToolRegistry
└── guard.py      # 已有 ToolGuard
```

每个 Tool 独立文件，避免将“文件系统”固化为一个封闭工具包。工具的名称、输入 schema 和行为是 Skill 编排的稳定契约；同一名称的内部实现以后可以替换，不修改 Skill。

现有 `filesystem.py` 与 `ReadFileTool` 会被移除。引用它的主 Agent 和 Subagent 配置改为导入 `ReadTool`；主 Agent 的工具名称从 `read_file` 迁移为 `read`。

## 工具契约

### `read`

```json
{
  "path": "README.md",
  "offset": 1,
  "limit": 2000
}
```

- `path` 必填，支持相对当前工作区和绝对路径。
- `offset` 是从 1 开始的文本行号，默认 1。
- `limit` 是最大读取行数，默认 2000。
- 结果带行号；超过限制时在末尾说明可以继续读取的行号。
- 只读取 UTF-8 文本；不存在、目录、解码失败或 I/O 失败返回 `ToolResult(ok=False, ...)`。

### `write`

```json
{
  "path": "notes/today.md",
  "content": "# 今日事项\n"
}
```

- `path` 与 `content` 必填。
- 自动创建父目录；以 UTF-8 创建或完整覆盖目标文件。
- 成功结果返回写入路径和字符数；I/O 失败返回失败结果。

### `edit`

```json
{
  "path": "README.md",
  "old_string": "旧内容",
  "new_string": "新内容"
}
```

- 三个字段都必填。
- 仅当 `old_string` 在目标 UTF-8 文件中精确出现一次时才替换。
- 未匹配或出现多次时返回失败，文件不产生修改。
- 成功结果返回已修改路径。

### `bash`

```json
{
  "command": "git status --short",
  "timeout_seconds": 30,
  "cwd": "."
}
```

- `command` 必填；通过 `bash -lc` 执行。
- `cwd` 可选，默认项目根目录；相对路径相对于项目根目录。
- `timeout_seconds` 可选，默认 30 秒，最大 120 秒；超时返回失败结果。
- 结果包含退出码、标准输出和标准错误；输出总长度截断到固定上限，防止模型上下文失控。
- 本阶段不做命令黑名单、确认或权限拦截。

## 运行时组装

当 `[tooling].enabled = true` 时，`bootstrap/container.py` 按固定顺序注册：

```text
read → bash → edit → write
```

这与 Pi 的默认顺序一致，并使 `ToolRegistry.select_openai_tools()` 能根据用户输入选取这些工具。四个 Tool 均通过现有 `ToolRegistry.execute()` 和 `ToolGuard` 调用；本阶段不扩展 Guard 的授权策略。

文件修改类 Tool（`write`、`edit`）和 `bash` 使用现有 `write` 风险等级，`read` 使用 `read-only`。风险元数据先用于追踪和重试策略，后续确认机制可在同一位置接入。

Subagent profile 仅迁移现有读取依赖到 `ReadTool`，不会新增 `write`、`edit` 或 `bash`。

## Skill 编排

普通 Skill 的 frontmatter 使用标准工具名：

```yaml
requires_tools: [read, bash, edit, write]
```

例如“从 Git 仓库安装 Skill”的上层 Skill 可先用 `bash` 拉取或查询仓库、用 `read` 检查候选 `SKILL.md`、再用 `write` 或 `edit` 写入本机安装目录。Skill 只描述步骤，不直接拥有进程或文件操作权限。

## 测试

- `read`：成功读取、行范围、缺失文件、目录、非 UTF-8 文件。
- `write`：创建嵌套文件、覆盖已有文件、I/O 失败。
- `edit`：唯一精确替换、零次匹配、多次匹配且文件保持不变。
- `bash`：成功命令、非零退出码、超时、相对 `cwd`。
- 组装：主 Agent 注册四个标准名称；Subagent 只保留 `read`。
- 回归：现有普通 Skill 的 `requires_tools` 测试改用 `read`；Drift 测试保持 `read_file` 与 `write_file` 不变。

## 验收

重启 `./scripts/dev.sh` 后，通过任一已配置 IM 发送：

1. “读取 README.md 的前 20 行”；
2. “在 .flow/skills/test/SKILL.md 写入一个测试 Skill”；
3. “将该 Skill 描述中的测试改成验收”；
4. “执行 git status --short”。

四次操作分别触发 `read`、`write`、`edit`、`bash`，并在会话追踪中显示对应工具调用。
