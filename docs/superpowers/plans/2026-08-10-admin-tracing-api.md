# 管理追踪 API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供仅绑定本机、只读且不泄露会话内容的 FastAPI 追踪查询 API。

**Architecture:** `interfaces.admin` 负责 HTTP 契约、Pydantic 输出模型与安全摘要；应用层的 `TraceTimeline` 订阅既有 `EventBus`，将生命周期事件归一化为内存中的回合与事件记录。`ServiceApp` 在启动时创建该查询服务并管理独立的 Uvicorn 服务器，使浏览器从不直接访问 `.flow` 或 SQLite。

**Tech Stack:** Python 3.11、FastAPI、Uvicorn、Pydantic v2、pytest。

## Global Constraints

- 服务默认仅绑定 `127.0.0.1`，基础路径为 `/api`。
- 只实现 `GET /api/traces`、`GET /api/traces/{trace_id}` 和 `GET /api/events`。
- 列表默认 `limit=20`，仅允许 1–100；状态仅允许 `running`、`completed`、`failed`、`cancelled`、`unknown`。
- 时间以 ISO 8601 UTC 输出，耗时为整数毫秒。
- 不返回用户消息、模型完整输出、Token、工具参数、工具结果、原始 metadata 或完整 session id。
- 未知 trace 返回 `404`，参数校验错误返回 `422` 且使用 `{"detail": "..."}` 格式。

---

### Task 1: 建立应用层安全追踪时间线

**Files:**
- Create: `backend/src/application/agent/app/tracing.py`
- Modify: `backend/src/application/agent/app/__init__.py`
- Test: `backend/tests/agent/test_tracing.py`

**Interfaces:**
- Consumes: `infra.bus.event.Event`，其 `event_type`、`timestamp`、`trace_id`、`session_id` 和 `payload`。
- Produces: `TraceTimeline.record(event: Event) -> None`、`TraceTimeline.list_traces(limit: int, status: str | None, channel: str | None) -> list[TraceRecord]`、`TraceTimeline.get_trace(trace_id: str) -> TraceRecord | None` 和 `TraceTimeline.list_events(limit: int, trace_id: str | None, event_type: str | None) -> list[TimelineEvent]`。

- [ ] **Step 1: Write the failing timeline tests**

```python
def test_timeline_returns_completed_trace_with_safe_events():
    timeline = TraceTimeline()
    timeline.record(Event("turn_started", trace_id="trace-1", payload={"channel": "telegram"}))
    timeline.record(Event("tool_call_started", trace_id="trace-1", payload={"tool_args": {"secret": "x"}}))
    timeline.record(Event("turn_committed", trace_id="trace-1", payload={"assistant_output": "private"}))

    trace = timeline.get_trace("trace-1")
    assert trace is not None
    assert trace.status == "completed"
    assert [event.type for event in trace.events] == ["turn_started", "tool_started", "turn_committed"]
    assert all("private" not in event.summary for event in trace.events)
```

- [ ] **Step 2: Run the focused test and verify the expected missing-module failure**

Run: `cd backend && uv run pytest -q tests/agent/test_tracing.py`

Expected: FAIL during collection because `application.agent.app.tracing` does not exist.

- [ ] **Step 3: Implement the minimal event-to-timeline mapper**

```python
class TraceTimeline:
    def record(self, event: Event) -> None:
        # 按 trace_id 聚合开始、结束、渠道和状态；仅保存事件类型、时间和固定安全摘要。
        ...

    def list_traces(self, limit: int, status: str | None, channel: str | None) -> list[TraceRecord]:
        # 以 started_at 倒序筛选，返回切片。
        ...
```

Map `turn_started` to `running`, `turn_committed` to `completed`, `turn_phase_error` to `failed`, and tool lifecycle names to `tool_started` / `tool_finished`. Ignore events without a trace id and retain no payload values other than the channel string.

- [ ] **Step 4: Run the focused timeline tests and verify they pass**

Run: `cd backend && uv run pytest -q tests/agent/test_tracing.py`

Expected: PASS.

### Task 2: 定义管理 HTTP 契约与查询路由

**Files:**
- Create: `backend/src/interfaces/admin/__init__.py`
- Create: `backend/src/interfaces/admin/schemas.py`
- Create: `backend/src/interfaces/admin/router.py`
- Test: `backend/tests/interfaces/test_admin_tracing_api.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Consumes: `TraceTimeline` 的四个查询方法。
- Produces: `create_admin_app(timeline: TraceTimeline) -> FastAPI`，其中所有路由挂载在 `/api`。

- [ ] **Step 1: Write the failing API tests**

```python
def test_traces_applies_status_and_channel_filters(client):
    response = client.get("/api/traces?limit=1&status=completed&channel=telegram")
    assert response.status_code == 200
    assert response.json() == [{"id": "trace-1", "channel": "telegram", "status": "completed", "started_at": "2026-08-10T10:00:00Z", "duration_ms": 4210}]

def test_unknown_trace_returns_contract_404(client):
    response = client.get("/api/traces/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "未找到追踪记录: missing"}
```

Also cover ascending detail events, descending `/api/events`, `trace_id` and `type` filtering, limit validation, and the absence of sensitive payload fields.

- [ ] **Step 2: Run the focused API test and verify the expected missing-module failure**

Run: `cd backend && uv run pytest -q tests/interfaces/test_admin_tracing_api.py`

Expected: FAIL during collection because `interfaces.admin.router` and FastAPI are absent.

- [ ] **Step 3: Add the dependencies, response schemas and routes**

```python
@router.get("/traces", response_model=list[TraceSummary])
def list_traces(
    limit: Annotated[int, Query(20, ge=1, le=100)] = 20,
    status: TraceStatus | None = None,
    channel: str | None = None,
) -> list[TraceSummary]:
    return [TraceSummary.model_validate(row) for row in timeline.list_traces(limit, status, channel)]
```

Add `fastapi` and `uvicorn` as project dependencies. Define separate `TraceSummary`、`TraceDetail` and `TraceEvent` Pydantic models with only the contract fields. `GET /traces/{trace_id}` raises `HTTPException(404, detail=f"未找到追踪记录: {trace_id}")`; `GET /events` accepts only the documented filters.

- [ ] **Step 4: Run the focused API tests and verify they pass**

Run: `cd backend && uv run pytest -q tests/interfaces/test_admin_tracing_api.py`

Expected: PASS.

### Task 3: 装配生命周期与本机 HTTP 服务器

**Files:**
- Create: `backend/src/interfaces/admin/server.py`
- Modify: `backend/src/infra/config.py`
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/src/bootstrap/service_app.py`
- Modify: `config.example.toml`
- Test: `backend/tests/infrastructure/test_admin_service_lifecycle.py`

**Interfaces:**
- Consumes: `TraceTimeline`、`create_admin_app` 和 `EventBus.on_any`。
- Produces: `AdminServer.start() -> None`、`AdminServer.stop() -> None`、`AdminServer.join(timeout: float | None) -> None`；`AdminApiConfig(enabled: bool = True, host: str = "127.0.0.1", port: int = 8790)`。

- [ ] **Step 1: Write failing lifecycle and wiring tests**

```python
def test_service_wires_every_event_into_admin_timeline():
    event_bus = EventBus()
    timeline = TraceTimeline()
    event_bus.on_any(timeline.record)
    event_bus.publish(Event("turn_started", trace_id="trace-1"))
    assert timeline.get_trace("trace-1") is not None

def test_admin_server_binds_localhost_only():
    config = AdminApiConfig()
    assert config.host == "127.0.0.1"
```

- [ ] **Step 2: Run the focused lifecycle test and verify the expected missing-module failure**

Run: `cd backend && uv run pytest -q tests/infrastructure/test_admin_service_lifecycle.py`

Expected: FAIL because `AdminApiConfig` and the server integration do not exist.

- [ ] **Step 3: Implement configuration and ServiceApp lifecycle ownership**

```python
timeline = TraceTimeline()
event_bus.on_any(timeline.record)
admin_server = AdminServer(
    app=create_admin_app(timeline), host=cfg.admin_api.host, port=cfg.admin_api.port
)
```

Add `admin_api` to `AppConfig`; reject hosts other than `127.0.0.1` and `localhost`. Return the timeline and server from `create_app_runtime`; in `ServiceApp.start()` start the server after channels and stop/join it before releasing the workspace lock. Do not start it when `enabled` is false. Add a commented `[admin_api]` block to `config.example.toml` without credentials.

- [ ] **Step 4: Run lifecycle and interface regression tests**

Run: `cd backend && uv run pytest -q tests/interfaces/test_admin_tracing_api.py tests/infrastructure/test_admin_service_lifecycle.py tests/infrastructure/test_config.py`

Expected: PASS.

### Task 4: 完成静态检查与全量验证

**Files:**
- Modify: only files created or modified by Tasks 1–3 if formatting or type checks identify a defect.

**Interfaces:**
- Consumes: completed tracing timeline, router and lifecycle server.
- Produces: verified implementation of the API contract.

- [ ] **Step 1: Format the changed backend files**

Run: `cd backend && uv run black src/application/agent/app/tracing.py src/interfaces/admin tests/agent/test_tracing.py tests/interfaces/test_admin_tracing_api.py tests/infrastructure/test_admin_service_lifecycle.py`

- [ ] **Step 2: Run the backend test suite**

Run: `cd backend && uv run pytest -q`

Expected: PASS with no failing tests.

- [ ] **Step 3: Run static type checks**

Run: `cd backend && uv run pyright`

Expected: PASS with zero errors.

## 自检

- 契约的三个 GET 路由、状态和 limit 约束分别由任务 1–2 覆盖。
- 本机绑定、FastAPI 生命周期和事件总线接线由任务 3 覆盖。
- 用户输入、模型输出、工具参数/结果、metadata 与完整 session id 均不会进入 `TraceRecord` 或 Pydantic 响应。
- 当前范围不包含认证、SSE、WebSocket、任务控制、配置修改或数据库直连。
