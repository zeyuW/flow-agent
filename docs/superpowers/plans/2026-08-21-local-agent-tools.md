# 本地 Agent 原子工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为主 Agent 提供独立、可组合的 `read`、`write`、`edit`、`bash` 四个本地执行 Tool。

**Architecture:** 以四个独立模块实现四个稳定 Tool 契约，并继续通过现有 `ToolRegistry` 注册、选择和调用。主 Agent 注册全部四项；Subagent 仅将既有读取依赖从 `ReadFileTool` 迁移为 `ReadTool`；Drift 内部工具不修改。

**Tech Stack:** Python 3.11+、subprocess、pytest、Pyright、Black。

**Spec:** `docs/superpowers/specs/2026-08-21-local-agent-tools-design.md`

## Global Constraints

- Tool 注册名固定为 `read`、`write`、`edit`、`bash`。
- 四个 Tool 分别放在 `read.py`、`write.py`、`edit.py`、`bash.py`；不创建 `filesystem.py` 聚合层。
- 本阶段不增加 IM 授权、二次确认、命令黑名单、沙箱或跨平台 Shell 适配。
- `bash` 使用 `bash -lc`，默认项目根目录，默认 30 秒、最大 120 秒超时，并截断输出。
- `edit` 仅在 `old_string` 精确出现一次时写入；失败时不得修改文件。
- Drift 管线继续使用内部 `read_file`、`write_file`；用户自行管理 Git 提交，本计划不执行提交。

---

## 文件结构

- Create: `backend/src/application/capabilities/tools/read.py` — `ReadTool` 与行范围读取。
- Create: `backend/src/application/capabilities/tools/write.py` — `WriteTool` 与文件创建/覆盖。
- Create: `backend/src/application/capabilities/tools/edit.py` — `EditTool` 的唯一精确替换。
- Create: `backend/src/application/capabilities/tools/bash.py` — `BashTool` 的受限时间命令执行。
- Delete: `backend/src/application/capabilities/tools/filesystem.py` — 旧 `ReadFileTool`。
- Modify: `backend/src/bootstrap/container.py` — 主 Agent 注册四个 Tool 与风险元数据。
- Modify: `backend/src/application/delegation/app/profiles.py` — 迁移读取 Tool 导入。
- Modify: `backend/src/application/capabilities/tools/guard.py` — 把现有路径检查对应的工具名改为 `read`。
- Modify: 测试和普通 Skill 示例中引用 `read_file` 的主 Agent 契约。

## Task 1: 实现独立 `read` Tool 并迁移读取引用

**Files:**
- Create: `backend/src/application/capabilities/tools/read.py`
- Delete: `backend/src/application/capabilities/tools/filesystem.py`
- Modify: `backend/src/application/delegation/app/profiles.py`
- Modify: `backend/src/application/capabilities/tools/guard.py`
- Modify: `backend/tests/capabilities/tools/test_filesystem_tool.py`
- Modify: `backend/tests/capabilities/mcp/test_stage11_external.py`
- Modify: `backend/tests/interfaces/test_telegram_multimodal.py`

**Interfaces:**
- Produces `ReadTool.name == "read"` and `ReadTool.run({"path": str, "offset"?: int, "limit"?: int}) -> ToolResult`.
- Consumes no new service; later tasks and Subagent profiles import `ReadTool` from `application.capabilities.tools.read`.

- [ ] **Step 1: 写出 `read` 的失败测试**

```python
def test_read_tool_returns_numbered_line_range(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = ReadTool().run({"path": str(path), "offset": 2, "limit": 1})

    assert result.ok is True
    assert result.content == "2: two\n...<continue from line 3>"


def test_read_tool_rejects_directory(tmp_path: Path):
    result = ReadTool().run({"path": str(tmp_path)})
    assert result.ok is False
    assert "Not a file" in result.content
```

- [ ] **Step 2: 运行失败测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_read_tool.py -q`

Expected: FAIL，因为 `read.py` 和 `ReadTool` 尚不存在。

- [ ] **Step 3: 最小化实现并迁移引用**

实现 `ReadTool`：验证路径、`offset >= 1`、`limit >= 1`，按行读取 UTF-8 文本，逐行加 `"<line>: "` 前缀，并在有剩余内容时输出继续位置。保留缺失文件、目录、解码与 I/O 的失败结果。

删除 `filesystem.py`；把主 Agent 以外仍导入 `ReadFileTool` 的位置改为 `ReadTool`，并把普通 Skill 依赖测试的 `read_file` 改为 `read`。`ToolGuard` 仅把现有读取路径检查的名称改为 `read`。不改 Drift 工具代码。

- [ ] **Step 4: 运行读取回归测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_read_tool.py tests/capabilities/mcp/test_stage11_external.py tests/interfaces/test_telegram_multimodal.py tests/delegation -q`

Expected: PASS。

## Task 2: 实现独立 `write` 与 `edit` Tool

**Files:**
- Create: `backend/src/application/capabilities/tools/write.py`
- Create: `backend/src/application/capabilities/tools/edit.py`
- Create: `backend/tests/capabilities/tools/test_write_tool.py`
- Create: `backend/tests/capabilities/tools/test_edit_tool.py`

**Interfaces:**
- Produces `WriteTool.run({"path": str, "content": str}) -> ToolResult`。
- Produces `EditTool.run({"path": str, "old_string": str, "new_string": str}) -> ToolResult`。

- [ ] **Step 1: 写出写入与精确编辑的失败测试**

```python
def test_write_tool_creates_nested_file(tmp_path: Path):
    path = tmp_path / "notes" / "today.md"
    result = WriteTool().run({"path": str(path), "content": "# 今天\n"})
    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "# 今天\n"


def test_edit_tool_replaces_exactly_one_match(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("before old after", encoding="utf-8")
    result = EditTool().run({"path": str(path), "old_string": "old", "new_string": "new"})
    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "before new after"


def test_edit_tool_keeps_file_when_match_is_not_unique(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("old old", encoding="utf-8")
    result = EditTool().run({"path": str(path), "old_string": "old", "new_string": "new"})
    assert result.ok is False
    assert path.read_text(encoding="utf-8") == "old old"
```

- [ ] **Step 2: 运行失败测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_write_tool.py tests/capabilities/tools/test_edit_tool.py -q`

Expected: FAIL，因为 `write.py`、`edit.py` 与 Tool 类尚不存在。

- [ ] **Step 3: 最小化实现**

`WriteTool` 验证两个字符串输入，创建目标父目录并以 UTF-8 完整写入。`EditTool` 验证三个字符串输入，读取 UTF-8 文本，使用 `content.count(old_string)` 判断唯一性；仅计数为 1 时调用一次 `replace(old_string, new_string, 1)` 写回。所有 I/O 异常返回 `ToolResult(ok=False, ...)`。

- [ ] **Step 4: 运行写入与编辑测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_write_tool.py tests/capabilities/tools/test_edit_tool.py -q`

Expected: PASS。

## Task 3: 实现独立 `bash` Tool

**Files:**
- Create: `backend/src/application/capabilities/tools/bash.py`
- Create: `backend/tests/capabilities/tools/test_bash_tool.py`

**Interfaces:**
- Produces `BashTool(project_root: Path)`。
- Produces `BashTool.run({"command": str, "timeout_seconds"?: int, "cwd"?: str}) -> ToolResult`。

- [ ] **Step 1: 写出命令、工作目录和超时的失败测试**

```python
def test_bash_tool_uses_relative_working_directory(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    result = BashTool(tmp_path).run({"command": "pwd", "cwd": "work"})
    assert result.ok is True
    assert str(work) in result.content


def test_bash_tool_returns_failed_result_after_timeout(tmp_path: Path):
    result = BashTool(tmp_path).run({"command": "sleep 1", "timeout_seconds": 0})
    assert result.ok is False
    assert "timed out" in result.content
```

- [ ] **Step 2: 运行失败测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_bash_tool.py -q`

Expected: FAIL，因为 `bash.py` 和 `BashTool` 尚不存在。

- [ ] **Step 3: 最小化实现**

使用 `subprocess.run(["bash", "-lc", command], cwd=resolved_cwd, capture_output=True, text=True, timeout=timeout)`。默认超时 30，输入值规范化到 1 至 120；未提供 `cwd` 使用构造时传入的项目根目录，相对路径以项目根目录解析。将退出码、stdout、stderr 格式化为单个内容字符串，并对总长度做固定截断；非零退出码和 `TimeoutExpired` 返回 `ok=False`。

- [ ] **Step 4: 运行 Bash 测试**

Run: `cd backend && uv run pytest tests/capabilities/tools/test_bash_tool.py -q`

Expected: PASS。

## Task 4: 注册四个 Tool 并完成运行时回归

**Files:**
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/tests/capabilities/tools/test_registry.py` 或 Create: `backend/tests/bootstrap/test_core_tools.py`
- Modify: `docs/api.md`

**Interfaces:**
- Main `ToolRegistry.list_tool_names()` contains `read`、`bash`、`edit`、`write` when tooling is enabled.
- Risk metadata is `read-only` for `read`, `write` for `bash`、`edit`、`write`。

- [ ] **Step 1: 写出主 Agent 组装的失败测试**

```python
def test_core_components_register_local_agent_tools(config):
    components = create_core_components(config)
    tools = components["tool_registry"]
    assert {"read", "bash", "edit", "write"} <= tools.list_tool_names()
    assert tools.get_risk_level("read") == "read-only"
    assert tools.get_risk_level("bash") == "write"
```

- [ ] **Step 2: 运行失败测试**

Run: `cd backend && uv run pytest tests/bootstrap/test_core_tools.py -q`

Expected: FAIL，因为 container 尚未注册四个 Tool。

- [ ] **Step 3: 注册 Tool 并同步文档**

在 `create_core_components()` 的 `cfg.tooling.enabled` 分支按 `read`、`bash`、`edit`、`write` 注册四个 Tool。`BashTool` 接收 `WORKSPACE_LAYOUT.root`。使用 `register_with_meta()` 写入风险等级。更新 `docs/api.md` 的 Skill 示例，使用标准 `requires_tools` 名称。

- [ ] **Step 4: 运行定向回归测试**

Run: `cd backend && uv run pytest tests/bootstrap/test_core_tools.py tests/capabilities/tools tests/delegation -q`

Expected: PASS。

## Task 5: 完整验证与 IM 手动验收

**Files:**
- Modify: `docs/superpowers/specs/2026-08-21-local-agent-tools-design.md`（仅在实现发现必须澄清的契约时）

- [ ] **Step 1: 格式化并执行静态检查**

Run: `cd backend && uv run black src/application/capabilities/tools src/bootstrap/container.py src/application/delegation/app/profiles.py tests/capabilities/tools tests/bootstrap/test_core_tools.py`

Run: `cd backend && uv run pyright src/application/capabilities/tools src/bootstrap/container.py src/application/delegation/app/profiles.py`

Expected: Black 不再改动文件，Pyright 为 0 errors。

- [ ] **Step 2: 执行完整后端回归**

Run: `cd backend && uv run pytest -q`

Expected: PASS。

- [ ] **Step 3: 手动验证**

Run: `./scripts/dev.sh`

从已配置 IM 依次请求读取文件、写入 `.flow/skills/test/SKILL.md`、唯一文本替换和 `git status --short`；在会话追踪中确认工具名称分别是 `read`、`write`、`edit`、`bash`。
