# Skill 目录服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持项目与本机已安装两类普通 Skill 的统一发现，并把真实 Skill/MCP 状态展示到控制台。

**Architecture:** 新增只读 `SkillCatalog` 扫描三个明确来源，普通 Skill 仅以 `SKILL.md` frontmatter 作为描述。`CapabilityQueryService` 组合 catalog 与已有 `McpServerRegistry`，再由管理 API 和前端消费；内置 Skill 不进入管理 API 的 Skill 列表。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、pytest、Next.js、TypeScript、Zod、TanStack Query、Vitest。

**Spec:** `docs/superpowers/specs/2026-08-21-skill-catalog-design.md`

## Global Constraints

- 普通 Skill 只读取 `SKILL.md`；`.flow/drift/skills/` 不在本次范围内。
- 项目目录是 `<仓库根目录>/skills/`，已安装目录是 `<仓库根目录>/.flow/skills/`。
- 内置 Skill 可以参与运行期发现，但不得通过管理 API 返回给前端。
- 同名 Skill 不得静默覆盖；全部同名项以 `conflict` 状态返回。
- HTTP 响应不得暴露绝对路径、命令或环境变量。
- 用户自行管理 Git 提交；本计划不执行 `git add` 或 `git commit`。

---

## 文件结构

- Modify: `backend/src/infra/workspace.py` — 声明项目与已安装 Skill 的独立路径，并初始化各自 README。
- Modify: `backend/src/application/capabilities/skills/models.py` — 定义解析后的 Skill 与目录条目类型。
- Modify: `backend/src/application/capabilities/skills/loader.py` — 解析标准 YAML frontmatter 的 `SKILL.md`。
- Delete: `backend/src/application/capabilities/skills/manager.py` — 移除仍以 `skill.json` 为契约的旧管理器；安装管理留待市场阶段重新设计。
- Create: `backend/src/application/capabilities/skills/catalog.py` — 扫描来源、检测同名冲突、隐藏内置项。
- Create: `backend/src/application/capabilities/app/capability_query.py` — 组合 Skill catalog 与 MCP 运行状态。
- Modify: `backend/src/bootstrap/container.py`、`backend/src/bootstrap/service_app.py` — 构造并注入查询服务。
- Modify: `backend/src/interfaces/admin/schemas.py`、`backend/src/interfaces/admin/router.py` — 增加只读 `/api/capabilities` 契约。
- Modify: `frontend/src/lib/api/schemas.ts`、`frontend/src/lib/api/client.ts`、`frontend/src/app/page.tsx` — 请求并渲染真实能力数据。
- Create/Modify: `backend/tests/capabilities/skills/test_catalog.py`、`backend/tests/interfaces/test_admin_tracing_api.py`、`frontend/src/lib/api/client.test.ts`、`frontend/src/app/page.test.tsx`。

## Task 1: 确立 Skill 路径与标准解析

**Files:**
- Modify: `backend/src/infra/workspace.py`
- Modify: `backend/src/application/capabilities/skills/models.py`
- Modify: `backend/src/application/capabilities/skills/loader.py`
- Delete: `backend/src/application/capabilities/skills/manager.py`
- Modify: `backend/tests/infrastructure/test_stage18_workspace_commands.py`
- Create: `backend/tests/capabilities/skills/test_loader.py`

**Interfaces:**
- Produces `SkillSpec(name, description, path, requires_tools, requires_sources, requires_mcp, requires_vision_model, requires_image_output)` from one `SKILL.md`.
- Produces `WorkspaceLayout.project_skills_dir` and `WorkspaceLayout.installed_skills_dir`.

- [ ] **Step 1: 写出路径与 frontmatter 的失败测试**

```python
def test_workspace_has_project_and_installed_skill_directories(tmp_path: Path):
    layout = init_workspace(tmp_path)
    assert layout.project_skills_dir == tmp_path / "skills"
    assert layout.installed_skills_dir == tmp_path / ".flow" / "skills"
    assert (layout.project_skills_dir / "README.md").is_file()


def test_loader_parses_yaml_frontmatter_and_dependencies(tmp_path: Path):
    skill = tmp_path / "daily-news"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\\nname: daily-news\\ndescription: 每日新闻摘要\\n"
        "requires_mcp: [news, browser]\\n---\\n# Daily news\\n",
        encoding="utf-8",
    )
    spec = SkillLoader(tmp_path).load()[0]
    assert spec.name == "daily-news"
    assert spec.requires_mcp == ["news", "browser"]
```

- [ ] **Step 2: 运行失败测试**

Run: `cd backend && uv run pytest tests/infrastructure/test_stage18_workspace_commands.py tests/capabilities/skills/test_loader.py -q`

Expected: FAIL，因为新路径字段和 YAML frontmatter 解析尚不存在。

- [ ] **Step 3: 最小化实现路径与解析器**

在 `WorkspaceLayout` 中保留 `drift_skills_dir`，将原 `.flow/skills` 明确为 `installed_skills_dir`，并新增根目录 `project_skills_dir`。初始化时创建两个目录和中文 README。更新调用 `skills_dir` 的工作区测试；删除未被运行期使用、且仍依赖 `skill.json` 的 `SkillManager` 及其测试导入。

在 `SkillLoader` 中只遍历 `*/SKILL.md`，先读取 YAML frontmatter；将列表字段接受为 YAML 列表或逗号分隔文本。frontmatter 缺失、名称非法或字段类型非法时跳过该文件并记录日志，不能中断其它 Skill 的扫描。

- [ ] **Step 4: 运行目标测试**

Run: `cd backend && uv run pytest tests/infrastructure/test_stage18_workspace_commands.py tests/capabilities/skills/test_loader.py -q`

Expected: PASS。

## Task 2: 实现多来源 Skill catalog 与冲突规则

**Files:**
- Create: `backend/src/application/capabilities/skills/catalog.py`
- Modify: `backend/src/application/capabilities/skills/models.py`
- Create: `backend/tests/capabilities/skills/test_catalog.py`

**Interfaces:**
- Consumes `SkillLoader.load() -> list[SkillSpec]`。
- Produces `SkillCatalog.list_items(include_builtin: bool = False) -> list[SkillCatalogItem]`。
- `SkillCatalogItem` 包含 `name`、`description`、`source`、`status`、`reason` 和内部 `spec`，其中 `source` 是 `builtin`、`project` 或 `installed`，`status` 是 `available` 或 `conflict`。

- [ ] **Step 1: 写出来源、隐藏内置和冲突的失败测试**

```python
def test_catalog_lists_project_and_installed_skills(tmp_path: Path):
    write_skill(tmp_path / "skills", "weekly-report", "项目周报")
    write_skill(tmp_path / ".flow" / "skills", "personal-notes", "个人笔记")
    items = SkillCatalog(tmp_path / "builtin", tmp_path / "skills", tmp_path / ".flow" / "skills").list_items()
    assert [(item.name, item.source) for item in items] == [
        ("personal-notes", "installed"), ("weekly-report", "project")
    ]


def test_catalog_marks_same_name_as_conflict(tmp_path: Path):
    write_skill(tmp_path / "skills", "report", "项目版本")
    write_skill(tmp_path / ".flow" / "skills", "report", "本机版本")
    items = SkillCatalog(tmp_path / "builtin", tmp_path / "skills", tmp_path / ".flow" / "skills").list_items()
    assert {item.status for item in items} == {"conflict"}
    assert all(item.reason == "同名 Skill 冲突" for item in items)
```

- [ ] **Step 2: 运行 catalog 测试确认失败**

Run: `cd backend && uv run pytest tests/capabilities/skills/test_catalog.py -q`

Expected: FAIL，因为 `SkillCatalog` 尚不存在。

- [ ] **Step 3: 实现 catalog**

按 builtin、project、installed 三个根目录分别创建 loader，给结果标记来源。按名称分组，出现多条时把该组每项标记为 `conflict` 与“同名 Skill 冲突”；否则标记为 `available`。默认过滤 `builtin`，但提供 `include_builtin=True` 给运行期调用。按 `name`、`source` 稳定排序，保证 API 和测试稳定。

- [ ] **Step 4: 运行 catalog 测试**

Run: `cd backend && uv run pytest tests/capabilities/skills/test_catalog.py -q`

Expected: PASS。

## Task 3: 建立能力查询服务和管理 API

**Files:**
- Create: `backend/src/application/capabilities/app/__init__.py`
- Create: `backend/src/application/capabilities/app/capability_query.py`
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/src/bootstrap/service_app.py`
- Modify: `backend/src/interfaces/admin/schemas.py`
- Modify: `backend/src/interfaces/admin/router.py`
- Modify: `backend/tests/interfaces/test_admin_tracing_api.py`

**Interfaces:**
- Consumes `SkillCatalog.list_items()` 和 `McpServerRegistry.list_servers()`。
- Produces `CapabilityQueryService.get_capabilities() -> CapabilitySnapshot`。
- Exposes `GET /api/capabilities`，JSON 仅含 `skills[{name, description, source, status, reason}]` 与 `connectors[{name, connected, tools}]`。

- [ ] **Step 1: 写出管理 API 的失败测试**

```python
class _CapabilityQuery:
    def get_capabilities(self):
        return {
            "skills": [{"name": "weekly-report", "description": "项目周报", "source": "project", "status": "available", "reason": None}],
            "connectors": [{"name": "ai-news", "connected": True, "tools": ["news_search"]}],
        }


def test_capabilities_route_returns_safe_skill_and_connector_data():
    app = create_admin_app(TraceTimeline(), _SessionQuery(), _Scheduler(), _CapabilityQuery())
    response = TestClient(app).get("/api/capabilities")
    assert response.status_code == 200
    assert response.json()["skills"][0]["source"] == "project"
    assert "path" not in response.text
    assert "command" not in response.text
```

- [ ] **Step 2: 运行路由测试确认失败**

Run: `cd backend && uv run pytest tests/interfaces/test_admin_tracing_api.py -q`

Expected: FAIL，因为路由构造函数与 `/api/capabilities` 尚不存在。

- [ ] **Step 3: 实现查询服务与注入**

`CapabilityQueryService` 只将 catalog 公开字段映射为字典，并把 MCP `list_servers()` 的 `name`、`connected`、`tools` 复制到连接器结果。`container.py` 使用 `WORKSPACE_LAYOUT` 的三个 Skill 根目录构造 catalog 和查询服务；`create_app_runtime()` 在返回元组末尾加入该服务，`ServiceApp` 保存并传给 `create_admin_app()`。

为 API 添加 Pydantic 响应模型，`source`、`status` 采用 `Literal` 限制。路由通过查询服务返回快照，不能读取路径或 registry 私有字段。

- [ ] **Step 4: 运行 API 测试**

Run: `cd backend && uv run pytest tests/interfaces/test_admin_tracing_api.py -q`

Expected: PASS。

## Task 4: 用真实 API 替换能力页示例卡片

**Files:**
- Modify: `frontend/src/lib/api/schemas.ts`
- Modify: `frontend/src/lib/api/client.ts`
- Modify: `frontend/src/lib/api/client.test.ts`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/page.test.tsx`
- Modify: `frontend/src/styles/globals.css`（仅空状态或状态标签需要样式时）

**Interfaces:**
- Consumes `getCapabilities(): Promise<CapabilitySnapshot>`。
- Renders project/installed Skill cards and MCP connector cards without built-in Skill cards.

- [ ] **Step 1: 写出客户端和页面失败测试**

```tsx
it("从能力 API 读取项目与已安装 Skill", async () => {
  vi.mocked(getCapabilities).mockResolvedValue({
    skills: [
      { name: "weekly-report", description: "项目周报", source: "project", status: "available", reason: null },
      { name: "personal-notes", description: "个人笔记", source: "installed", status: "available", reason: null }
    ],
    connectors: [{ name: "ai-news", connected: true, tools: ["news_search"] }]
  });
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));
  expect(await screen.findByText("weekly-report")).toBeInTheDocument();
  expect(screen.getByText("项目 Skill")).toBeInTheDocument();
  expect(screen.getByText("已安装 Skill")).toBeInTheDocument();
  expect(screen.getByText("1 个工具")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行前端测试确认失败**

Run: `cd frontend && npm run test -- --run src/lib/api/client.test.ts src/app/page.test.tsx`

Expected: FAIL，因为 `getCapabilities`、schema 和真实页面渲染尚不存在。

- [ ] **Step 3: 实现 Zod 契约、客户端与页面状态**

新增 `capabilitySnapshotSchema`，客户端请求 `/api/capabilities`。`CapabilitiesPage` 使用 query：加载时显示简洁加载文本，失败时展示“无法读取技能与连接器”，成功时按 API 条目渲染卡片。来源标签固定映射 `project -> 项目 Skill`、`installed -> 已安装 Skill`；连接器显示“已连接/未连接”和“n 个工具”。Skill 为空时显示“尚未添加项目或已安装 Skill”；不渲染内置来源，即使后端异常返回该来源也在客户端过滤。

- [ ] **Step 4: 运行前端目标测试**

Run: `cd frontend && npm run test -- --run src/lib/api/client.test.ts src/app/page.test.tsx`

Expected: PASS。

## Task 5: 端到端验证与文档同步

**Files:**
- Modify: `docs/api.md`
- Modify: `README.md` 或 `backend/README.md`（仅现有 Skill 路径说明所在文件）
- Modify: `docs/superpowers/specs/2026-08-21-skill-catalog-design.md`（仅实施时发现的必要澄清）

**Interfaces:**
- Verifies the exact public API from Task 3 and UI behavior from Task 4.

- [ ] **Step 1: 更新普通 Skill 文档**

将普通 Skill 位置改为 `skills/<name>/SKILL.md` 与 `.flow/skills/<name>/SKILL.md`，删除普通 Skill 需要 `skill.json` 的说明；明确 `.flow/drift/skills/` 不受影响。

- [ ] **Step 2: 执行后端验证**

Run: `cd backend && uv run pytest -q`

Expected: PASS。

Run: `cd backend && uv run pyright src/application/capabilities/skills src/application/capabilities/app src/interfaces/admin src/bootstrap/container.py src/bootstrap/service_app.py`

Expected: 0 errors in changed modules。

- [ ] **Step 3: 执行前端验证**

Run: `cd frontend && npm run test && npm run typecheck && npm run lint && npm run build`

Expected: all commands exit 0。

- [ ] **Step 4: 进行手动验收**

Run: `./scripts/dev.sh`

在浏览器打开“技能与连接器”：确认项目 `skills/` 中的 Skill 以“项目 Skill”出现，`.flow/skills/` 中的 Skill 以“已安装 Skill”出现，MCP 卡片数量和连接状态与运行日志一致；没有 Skill 时显示空状态。
