# 会话 API 接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将会话页示例数据替换为支持多 IM 渠道、可按日期查询的本机历史会话数据。

**Architecture:** 被动消息管道先生成 `channel:conversation_id` 会话键，避免不同渠道的同名会话混淆。应用层 `SessionQueryService` 通过既有 `SessionStore` 提供只读摘要与详情，组合根将其注入本机 Admin API；前端只在日期范围变化时加载摘要、在选中会话后加载完整消息。

**Tech Stack:** Python 3.11、SQLite、FastAPI、Pydantic、Next.js、React Query、Zod、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-08-21-session-api-integration-design.md`

## Global Constraints

- 管理 API 仅绑定本机地址，新增端点均为只读。
- 新会话键为 `channel:conversation_id`；渠道名不能为空且不得包含冒号。
- 不含冒号的已有会话键作为 `legacy` 渠道读取，保留原始键作为外部会话 ID。
- 列表接口不返回消息正文，默认最多 50 条、最大 100 条；详情接口按需返回正文。
- 列表日期按服务所在时区解释，范围为闭区间。
- 代码命名直接表达职责；不得引入通用仓库层、额外服务进程或写操作。

---

## 文件结构

- Create: `backend/src/application/passive/domain/session_key.py` — 创建和解析渠道感知会话键。
- Create: `backend/src/application/passive/app/session_query.py` — 会话摘要与详情的只读应用服务。
- Modify: `backend/src/application/passive/app/pipeline.py` — 新入站消息使用渠道感知键。
- Modify: `backend/src/application/passive/infra/session_store.py` — 提供受限的会话摘要 SQL 查询。
- Modify: `backend/src/bootstrap/container.py` — 构造并返回会话查询服务。
- Modify: `backend/src/bootstrap/service_app.py` — 将会话查询服务注入 Admin API。
- Modify: `backend/src/interfaces/admin/schemas.py` — 会话摘要、消息和详情响应模型。
- Modify: `backend/src/interfaces/admin/router.py` — 增加两个会话只读路由。
- Modify: `backend/tests/interfaces/test_admin_tracing_api.py` — 保留 Trace 回归并覆盖会话 API。
- Create: `backend/tests/passive/test_session_key.py` — 渠道会话键单元测试。
- Create: `backend/tests/passive/test_session_query.py` — 日期过滤、摘要、详情和旧键兼容测试。
- Modify: `frontend/src/lib/api/schemas.ts` — 会话 Zod Schema。
- Modify: `frontend/src/lib/api/client.ts` — 会话列表与详情客户端。
- Modify: `frontend/src/lib/api/client.test.ts` — 请求参数和响应校验测试。
- Modify: `frontend/src/app/page.tsx` — 删除示例会话，接入 React Query 数据与加载状态。
- Modify: `frontend/src/app/page.test.tsx` — 会话加载、选择、空数据和失败状态测试。

## Task 1: 渠道感知会话键

**Files:**
- Create: `backend/src/application/passive/domain/session_key.py`
- Modify: `backend/src/application/passive/app/pipeline.py:26-31`
- Test: `backend/tests/passive/test_session_key.py`

**Consumes:** `IncomingMessage.channel` 与 `IncomingMessage.conversation_id`。

**Produces:** `make_session_key(channel: str, conversation_id: str) -> str` 与 `split_session_key(key: str) -> tuple[str, str]`；被动管道将其作为 `TurnFlow.session_id`。

- [ ] **Step 1: 写出失败的会话键测试**

```python
from application.passive.domain.session_key import make_session_key, split_session_key


def test_channel_is_part_of_session_key():
    assert make_session_key("telegram", "123") == "telegram:123"
    assert make_session_key("qq", "123") == "qq:123"


def test_legacy_session_key_is_readable():
    assert split_session_key("123") == ("legacy", "123")


def test_split_keeps_colon_in_external_conversation_id():
    assert split_session_key("qq:group:123") == ("qq", "group:123")
```

- [ ] **Step 2: 运行测试并确认因模块不存在失败**

Run: `cd backend && uv run pytest tests/passive/test_session_key.py -q`

Expected: `ModuleNotFoundError`，因为 `session_key.py` 尚不存在。

- [ ] **Step 3: 实现最小键函数并接入管道**

```python
def make_session_key(channel: str, conversation_id: str) -> str:
    clean_channel = channel.strip().lower()
    if not clean_channel or ":" in clean_channel:
        raise ValueError("渠道名称不能为空且不能包含冒号")
    return f"{clean_channel}:{conversation_id}"


def split_session_key(key: str) -> tuple[str, str]:
    channel, separator, conversation_id = key.partition(":")
    if not separator or not channel:
        return "legacy", key
    return channel, conversation_id
```

将 `pipeline.py` 中的 `_conversation_id_of()` 改为调用 `make_session_key(inbound.channel, inbound.conversation_id)`；`chat_id` 继续使用原始 `inbound.conversation_id`，不改变渠道投递地址。

- [ ] **Step 4: 运行键与被动管道测试**

Run: `cd backend && uv run pytest tests/passive/test_session_key.py tests/passive/test_agent_loop_contract.py -q`

Expected: PASS。

- [ ] **Step 5: 提交此任务（Git 索引可写时）**

Run: `git add backend/src/application/passive/domain/session_key.py backend/src/application/passive/app/pipeline.py backend/tests/passive/test_session_key.py && git commit -m "feat: distinguish sessions by channel"`

## Task 2: 会话只读查询服务

**Files:**
- Modify: `backend/src/application/passive/infra/session_store.py:131-153`
- Create: `backend/src/application/passive/app/session_query.py`
- Test: `backend/tests/passive/test_session_query.py`

**Consumes:** `SessionStore` 的 SQLite 会话与消息表、Task 1 的 `split_session_key()`。

**Produces:** `SessionQueryService.list_sessions(start_date: date, end_date: date, limit: int) -> list[SessionSummary]` 与 `SessionQueryService.get_session(session_id: str) -> SessionDetail | None`。

- [ ] **Step 1: 写出摘要、日期与详情失败测试**

```python
def test_list_sessions_filters_by_local_calendar_date(store, query_service):
    store.upsert_session("telegram:1", updated_at="2026-08-21T02:00:00+00:00")
    store.insert_message("telegram:1", 1, "user", "今天的消息", ts="2026-08-21T02:00:00+00:00")
    store.upsert_session("qq:2", updated_at="2026-08-20T02:00:00+00:00")

    result = query_service.list_sessions(date(2026, 8, 21), date(2026, 8, 21), 50)

    assert [item.id for item in result] == ["telegram:1"]
    assert result[0].channel == "telegram"
    assert result[0].preview == "今天的消息"


def test_get_session_returns_user_and_assistant_messages(store, query_service):
    store.insert_message("qq:group:1", 1, "user", "你好", ts="2026-08-21T02:00:00+00:00")
    store.insert_message("qq:group:1", 2, "assistant", "你好，有什么可以帮你？", ["search"], ts="2026-08-21T02:00:01+00:00")

    detail = query_service.get_session("qq:group:1")

    assert [(item.role, item.content, item.tool_chain) for item in detail.messages] == [("user", "你好", []), ("assistant", "你好，有什么可以帮你？", ["search"])]
```

- [ ] **Step 2: 运行测试并确认查询服务不存在失败**

Run: `cd backend && uv run pytest tests/passive/test_session_query.py -q`

Expected: `ModuleNotFoundError`，因为 `session_query.py` 尚不存在。

- [ ] **Step 3: 增加受限摘要 SQL 与查询服务**

在 `SessionStore` 增加 `list_session_summaries(start_at: str, end_at: str, limit: int) -> list[dict[str, Any]]`。查询返回 `key`、创建时间、更新时间、消息数和按 `seq DESC` 取得的最后一条 `content`；条件为 `updated_at >= start_at AND updated_at < end_at`，按 `updated_at DESC` 排序，全部参数使用绑定参数。

在 `session_query.py` 定义 `SessionSummary`、`SessionMessage`、`SessionDetail` 不可变数据类。`list_sessions()` 校验日期顺序、将本机时区日期边界转为 ISO 时间戳、限制 `limit` 到 1–100；`get_session()` 只返回 `user`、`assistant` 角色，找不到会话时返回 `None`。

- [ ] **Step 4: 运行会话查询测试**

Run: `cd backend && uv run pytest tests/passive/test_session_query.py -q`

Expected: PASS。

- [ ] **Step 5: 提交此任务（Git 索引可写时）**

Run: `git add backend/src/application/passive/infra/session_store.py backend/src/application/passive/app/session_query.py backend/tests/passive/test_session_query.py && git commit -m "feat: add read-only session queries"`

## Task 3: 管理 API 与组合根注入

**Files:**
- Modify: `backend/src/bootstrap/container.py:110-198, 268-355`
- Modify: `backend/src/bootstrap/service_app.py:205-238`
- Modify: `backend/src/interfaces/admin/schemas.py`
- Modify: `backend/src/interfaces/admin/router.py:18-60`
- Modify: `backend/tests/interfaces/test_admin_tracing_api.py`

**Consumes:** Task 2 的 `SessionQueryService`。

**Produces:** `GET /api/sessions` 与 `GET /api/sessions/{session_id}`；现有 Trace 路由保持不变。

- [ ] **Step 1: 写出失败的 API 契约测试**

```python
def test_sessions_routes_return_summaries_and_details():
    routes = _routes_with_sessions()
    summaries = routes["/api/sessions"](start_date=date(2026, 8, 21), end_date=date(2026, 8, 21), limit=50)
    detail = routes["/api/sessions/{session_id}"]("telegram:1")

    assert summaries[0]["channel"] == "telegram"
    assert detail["messages"][0]["content"] == "你好"


def test_unknown_session_returns_404():
    with pytest.raises(HTTPException, match="未找到会话: missing"):
        _routes_with_sessions()["/api/sessions/{session_id}"]("missing")
```

- [ ] **Step 2: 运行测试并确认路由不存在失败**

Run: `cd backend && uv run pytest tests/interfaces/test_admin_tracing_api.py -q`

Expected: FAIL，因为 Admin API 尚未声明会话路由或构造函数未接收查询服务。

- [ ] **Step 3: 声明响应模型、路由与注入**

在 `interfaces/admin/schemas.py` 增加 `SessionSummary`、`SessionMessage`、`SessionDetail` Pydantic 模型；`SessionDetail` 继承摘要并增加 `messages`。

在 `create_admin_app(timeline, session_query)` 中声明列表路由，接收 `start_date: date`、`end_date: date`、`limit: Annotated[int, Query(ge=1, le=100)] = 50`；详情路由调用 `session_query.get_session(session_id)`，缺失时抛出 `HTTPException(404, detail=f"未找到会话: {session_id}")`。

在 `create_core_components()` 创建 `SessionQueryService(session_store)` 并返回；`create_app_runtime()` 将其追加到返回元组；`ServiceApp._initialize_runtime()` 解包后传给 `create_admin_app()`。接口层不得导入 `SessionStore`。

- [ ] **Step 4: 运行管理 API 与架构边界测试**

Run: `cd backend && uv run pytest tests/interfaces/test_admin_tracing_api.py tests/architecture/test_passive_boundaries.py -q`

Expected: PASS。

- [ ] **Step 5: 提交此任务（Git 索引可写时）**

Run: `git add backend/src/bootstrap/container.py backend/src/bootstrap/service_app.py backend/src/interfaces/admin/schemas.py backend/src/interfaces/admin/router.py backend/tests/interfaces/test_admin_tracing_api.py && git commit -m "feat: expose sessions through admin api"`

## Task 4: 前端会话 API 客户端

**Files:**
- Modify: `frontend/src/lib/api/schemas.ts`
- Modify: `frontend/src/lib/api/client.ts`
- Modify: `frontend/src/lib/api/client.test.ts`

**Consumes:** Task 3 的 JSON 响应。

**Produces:** `getSessions(startDate: string, endDate: string)` 与 `getSession(sessionId: string)`。

- [ ] **Step 1: 写出失败的客户端测试**

```typescript
it("按日期范围请求会话摘要", async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse([]));
  await getSessions("2026-08-20", "2026-08-21");
  expect(fetchMock).toHaveBeenCalledWith("/api/sessions?start_date=2026-08-20&end_date=2026-08-21&limit=50", expect.any(Object));
});
```

- [ ] **Step 2: 运行测试并确认导出不存在失败**

Run: `cd frontend && npm run test -- src/lib/api/client.test.ts`

Expected: FAIL，提示 `getSessions` 未导出。

- [ ] **Step 3: 实现 Zod Schema 与客户端函数**

在 `schemas.ts` 增加会话摘要、消息、详情 Schema；消息 `role` 仅接受 `user` 或 `assistant`，`tool_chain` 为字符串数组。

在 `client.ts` 添加：

```typescript
export function getSessions(startDate: string, endDate: string): Promise<SessionSummary[]> {
  const params = new URLSearchParams({ start_date: startDate, end_date: endDate, limit: "50" });
  return getJson(`/api/sessions?${params}`, z.array(sessionSummarySchema));
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return getJson(`/api/sessions/${encodeURIComponent(sessionId)}`, sessionDetailSchema);
}
```

- [ ] **Step 4: 运行客户端测试**

Run: `cd frontend && npm run test -- src/lib/api/client.test.ts src/lib/api/traces.test.ts`

Expected: PASS。

- [ ] **Step 5: 提交此任务（Git 索引可写时）**

Run: `git add frontend/src/lib/api/schemas.ts frontend/src/lib/api/client.ts frontend/src/lib/api/client.test.ts && git commit -m "feat: add session api client"`

## Task 5: 会话页接入真实数据

**Files:**
- Modify: `frontend/src/app/page.tsx:1-220`
- Modify: `frontend/src/app/page.test.tsx`

**Consumes:** Task 4 的 `getSessions()`、`getSession()`。

**Produces:** 会话页在日期筛选后显示真实摘要，选中会话后显示真实消息、工具链、加载/空/错误状态。

- [ ] **Step 1: 写出失败的页面行为测试**

```typescript
it("选中真实会话后显示 Agent 消息与工具链", async () => {
  vi.mocked(getSessions).mockResolvedValueOnce([{ id: "telegram:1", channel: "telegram", external_conversation_id: "1", created_at: "2026-08-21T02:00:00Z", updated_at: "2026-08-21T02:00:00Z", message_count: 2, preview: "你好" }]);
  vi.mocked(getSession).mockResolvedValueOnce({ id: "telegram:1", channel: "telegram", external_conversation_id: "1", created_at: "2026-08-21T02:00:00Z", updated_at: "2026-08-21T02:00:00Z", message_count: 2, preview: "你好", messages: [{ role: "assistant", content: "你好，有什么可以帮你？", timestamp: "2026-08-21T02:00:01Z", tool_chain: ["search"] }] });

  render(<OverviewPage />);

  expect(await screen.findByText("你好，有什么可以帮你？")).toBeInTheDocument();
  expect(screen.getByText("search")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试并确认仍显示示例数据导致失败**

Run: `cd frontend && npm run test -- src/app/page.test.tsx`

Expected: FAIL，因为页面未调用会话客户端。

- [ ] **Step 3: 以 React Query 替换示例会话**

删除 `Conversation` 类型与硬编码 `conversations`。保留日期筛选控件：今天、昨天和近 7 天计算对应范围；日期选择器以选中日期作为开始与结束日期。摘要查询键包含开始与结束日期，详情查询仅在选中 ID 存在时启用。

列表加载时显示“正在读取会话…”，空结果显示“这个日期没有会话记录。”，请求失败显示“无法读取会话记录。”；详情加载时显示“正在读取对话…”，失败显示“无法读取该会话。”。使用 `channel` 显示渠道标签，使用 `external_conversation_id` 显示标题，使用 `timestamp` 显示本地时间，`tool_chain` 非空时渲染标签。其他三个导航页保持静态数据。

- [ ] **Step 4: 运行页面与完整前端验证**

Run: `cd frontend && npm run test && npm run typecheck && npm run lint && npm run build`

Expected: 全部 PASS。

- [ ] **Step 5: 提交此任务（Git 索引可写时）**

Run: `git add frontend/src/app/page.tsx frontend/src/app/page.test.tsx && git commit -m "feat: show persisted agent sessions"`

## Task 6: 端到端回归验证

**Files:**
- Modify: 无。

**Consumes:** Tasks 1–5 的完整实现。

**Produces:** 可由本地服务与浏览器手动验证的真实会话页面。

- [ ] **Step 1: 运行后端完整验证**

Run: `cd backend && uv run pytest -q && uv run black --check src tests && uv run pyright`

Expected: 全部 PASS。

- [ ] **Step 2: 启动本地前后端服务**

Run: `./scripts/dev.sh`

Expected: 后端 Admin API 在 `127.0.0.1:8790` 启动，前端在浏览器中打开。

- [ ] **Step 3: 产生真实会话并检查 API**

使用已启用渠道发送消息；然后运行：

```bash
curl 'http://127.0.0.1:8790/api/sessions?start_date=2026-08-21&end_date=2026-08-21&limit=50'
```

Expected: 列表中的 `channel` 与发送渠道一致；点击浏览器中的对应会话后，用户与 Agent 消息显示在对话区。

- [ ] **Step 4: 检查最终变更**

Run: `git diff --check && git status --short`

Expected: 没有空白错误；列出本期变更文件。

- [ ] **Step 5: 创建最终提交（Git 索引可写时）**

Run: `git add backend frontend docs/superpowers/specs/2026-08-21-session-api-integration-design.md docs/superpowers/plans/2026-08-21-session-api-integration.md && git commit -m "feat: connect session history to console"`
