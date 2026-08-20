# Trace API 前端联调实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让控制台以最少代码正确消费已部署的 Trace REST API。

**Architecture:** 保留现有首页和 TanStack Query 轮询。将 Zod 模型与 `flow-agent-admin-api` 的公开响应精确对齐，删除没有后端实现的管理接口和 SSE 代码，使用 client contract tests 固化三个真实端点。

**Tech Stack:** Next.js 15、React 19、TypeScript、Zod、TanStack Query、Vitest。

**Spec:** `docs/superpowers/specs/2026-08-20-trace-api-integration-design.md`

## Global Constraints

- 浏览器只访问同源 `/api/*`，`ADMIN_API_BASE_URL` 仅用于 Next.js rewrite。
- 只使用 `/api/traces`、`/api/traces/{trace_id}` 和 `/api/events`。
- `/api/events` 是 REST 数组，页面以 30 秒轮询获取快照。
- 不引入 SSE、会话页面、写操作或新的依赖。
- API key、Token、消息正文和原始 metadata 不得写入浏览器存储。

---

### Task 1: 固化真实 Trace API 契约

**Files:**
- Modify: `frontend/src/lib/api/schemas.ts`
- Modify: `frontend/src/lib/api/client.test.ts`
- Modify: `frontend/src/lib/api/traces.test.ts`

**Interfaces:**
- Consumes: `GET /api/traces`、`GET /api/traces/{trace_id}` 与 `GET /api/events` 的后端 Pydantic 响应。
- Produces: `traceSummarySchema` 接受 `started_at: string | null`；`traceEventSchema` 接受可省略的 `error`；`getEvents()`、`getTraces()` 与 `getTrace()` 保持签名不变。

- [ ] **Step 1: 写入失败的实际响应测试**

在 `client.test.ts` 的事件样例中删除 `error`，并在 `traces.test.ts` 添加后端允许的空开始时间：

```ts
json: vi.fn().mockResolvedValue([
  { id: "trace-1", channel: "telegram", status: "running", started_at: null, duration_ms: 0 }
])
```

```ts
json: vi.fn().mockResolvedValue([
  { trace_id: "trace-1", type: "turn_started", at: "2026-08-10T13:41:03Z", status: "ok", summary: "收到渠道消息" }
])
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend && npm run test -- src/lib/api/client.test.ts src/lib/api/traces.test.ts`

Expected: FAIL，提示 `error` 或 `started_at` 与当前 schema 不匹配。

- [ ] **Step 3: 最小化调整 schema**

```ts
export const traceEventSchema = z.object({
  type: z.string(), at: z.string(), status: z.string(), summary: z.string(),
  error: z.string().nullable().optional(), trace_id: z.string().optional()
});

export const traceSummarySchema = z.object({
  id: z.string(), channel: z.string(), status: traceStatusSchema,
  started_at: z.string().nullable(), duration_ms: z.number().nonnegative()
});
```

- [ ] **Step 4: 运行契约测试并确认通过**

Run: `cd frontend && npm run test -- src/lib/api/client.test.ts src/lib/api/traces.test.ts`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib/api/schemas.ts frontend/src/lib/api/client.test.ts frontend/src/lib/api/traces.test.ts
git commit -m "fix: align trace API contracts"
```

### Task 2: 删除无后端支持的旧客户端

**Files:**
- Modify: `frontend/src/lib/api/client.ts`
- Delete: `frontend/src/lib/api/service-health.ts`
- Delete: `frontend/src/lib/api/service-health.test.ts`
- Delete: `frontend/src/lib/api/schemas.test.ts`
- Delete: `frontend/src/lib/realtime/use-live-overview.ts`
- Delete: `frontend/src/lib/realtime/use-live-overview.test.tsx`

**Interfaces:**
- Consumes: Task 1 的 Trace schema 与 `getJson`。
- Produces: client 只导出 `AdminApiError`、`getEvents`、`getTraces` 与 `getTrace`；页面继续使用 `refetchInterval: 30_000`。

- [ ] **Step 1: 写入 client 导出边界测试**

在 `client.test.ts` 添加：

```ts
import * as client from "./client";

it("只暴露已实现的 Trace REST 客户端", () => {
  expect(Object.keys(client).sort()).toEqual([
    "AdminApiError", "getEvents", "getTrace", "getTraces"
  ]);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd frontend && npm run test -- src/lib/api/client.test.ts`

Expected: FAIL，当前模块还导出未实现的 `/api/v1/admin/*` 和 SSE client。

- [ ] **Step 3: 删除旧实现与不再使用的测试**

将 `client.ts` 收敛为通用 `getJson` 与三个 Trace REST 函数。移除 `PageRequest`、分页 schema、运行总览 DTO、健康度工具及 `useLiveOverview`，不修改 `page.tsx` 的 30 秒轮询逻辑。

- [ ] **Step 4: 运行前端检查**

Run: `cd frontend && npm run lint && npm run typecheck && npm test`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib/api/client.ts frontend/src/lib/api/client.test.ts frontend/src/lib/api/schemas.ts
git rm frontend/src/lib/api/service-health.ts frontend/src/lib/api/service-health.test.ts frontend/src/lib/api/schemas.test.ts frontend/src/lib/realtime/use-live-overview.ts frontend/src/lib/realtime/use-live-overview.test.tsx
git commit -m "refactor: remove unsupported admin API clients"
```

### Task 3: 验证构建与真实服务路径

**Files:**
- Modify: `frontend/README.md`

**Interfaces:**
- Consumes: Task 1 与 Task 2 的 `/api/*` client。
- Produces: 文档包含三个已支持端点和本地联调配置；生产构建可通过。

- [ ] **Step 1: 更新 README 的实时数据说明**

将实时数据段落替换为：

```md
页面通过 `/api/traces`、`/api/traces/{trace_id}` 和 `/api/events` 获取 REST 快照，每 30 秒刷新一次。启动管理 API 后设置 `ADMIN_API_BASE_URL=http://127.0.0.1:8790`。
```

- [ ] **Step 2: 运行完整构建验证**

Run: `cd frontend && npm run build`

Expected: PASS，`/` 静态页面构建完成。

- [ ] **Step 3: 验证并行管理 API 路由**

Run: `cd /home/roco/flow-agent-admin-api/backend && uv run python -c "from application.agent.app.tracing import TraceTimeline; from interfaces.admin.router import create_admin_app; app = create_admin_app(TraceTimeline()); print([route.path for route in app.routes])"`

Expected: 输出包含 `/api/traces`、`/api/traces/{trace_id}` 和 `/api/events`。

- [ ] **Step 4: 提交**

```bash
git add frontend/README.md
git commit -m "docs: document trace API integration"
```
