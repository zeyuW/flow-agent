# Flow Agent 会话优先控制台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建以会话为主入口、以 Trace 和事件为诊断能力的只读前端控制台。

**Architecture:** `features/sessions` 通过同源 `/api` 读取后端提供的会话、消息和 Trace；`features/logs` 读取事件与 Trace。TanStack Query 每 30 秒读取 REST 快照，Zod 先验证 DTO 再渲染。

**Tech Stack:** Next.js 15、React 19、TypeScript、TanStack Query、Zod、Vitest、Testing Library、Tailwind CSS。

## Global Constraints

- 只修改 `frontend/`，不修改后端、Docker、Compose、根 README 或其他跨项目文档。
- 浏览器仅请求同源 `/api/*`；`ADMIN_API_BASE_URL` 仅由 Next.js 服务端读取。
- 不在浏览器存储 API key、Token、消息正文或其他密钥。
- 本期严格只读，不实现人工回复、暂停、删除、导出或重试。
- 完整正文只在授权成功时渲染；无权限、空数据与请求失败分别呈现。
- 后端为 REST 快照，使用 30 秒轮询，不实现伪 SSE 或聊天 token 流。

---

### Task 1: 重构分组导航与页面壳层

**Files:**
- Modify: `frontend/src/components/workbench-shell.tsx`
- Modify: `frontend/src/styles/globals.css`
- Create: `frontend/src/app/sessions/page.tsx`
- Create: `frontend/src/app/logs/page.tsx`
- Test: `frontend/src/components/workbench-shell.test.tsx`

**Interfaces:** Produces enabled `/`、`/sessions`、`/logs` routes. Other navigation items use non-interactive `aria-disabled="true"` text.

- [ ] **Step 1: Write the failing navigation test**

```tsx
it("按调查分组展示会话与运行日志", () => {
  render(<WorkbenchShell details={null} header={null}>内容</WorkbenchShell>);
  expect(screen.getByText("调查")).toBeVisible();
  expect(screen.getByRole("link", { name: "会话与回合" })).toHaveAttribute("href", "/sessions");
  expect(screen.getByRole("link", { name: "运行日志" })).toHaveAttribute("href", "/logs");
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm run test -- src/components/workbench-shell.test.tsx`

Expected: FAIL because grouped navigation does not exist.

- [ ] **Step 3: Implement minimal navigation and placeholder routes**

Create navigation groups `调查`、`运行`、`知识与扩展`、`系统`; make only `概览`、`会话与回合`、`运行日志` links. Give `/sessions` and `/logs` semantic `h1` placeholders without data fetching.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend && npm run lint && npm run typecheck && npm run test -- src/components/workbench-shell.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/components/workbench-shell.tsx frontend/src/styles/globals.css frontend/src/app/sessions/page.tsx frontend/src/app/logs/page.tsx frontend/src/components/workbench-shell.test.tsx && git commit -m "feat: group control plane navigation"`

### Task 2: 建立会话、消息与 Trace 的类型化客户端

**Files:**
- Modify: `frontend/src/lib/api/schemas.ts`
- Modify: `frontend/src/lib/api/client.ts`
- Create: `frontend/src/lib/api/sessions.test.ts`

**Interfaces:** Produces `SessionSummary`、`SessionDetail`、`SessionMessage`、`SessionPageRequest`, `getSessions(request)`, `getSession(id)`, and `getSessionMessages(id, request)`.

- [ ] **Step 1: Write the failing contract test**

```ts
it("解析会话分页响应并发送筛选参数", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: vi.fn().mockResolvedValue({ items: [{ id: "s-1", channel: "telegram", user_display_name: "Alice", user_id_masked: "12…89", last_activity_at: "2026-08-10T00:00:00Z", status: "active", last_message_summary: "你好" }], next_cursor: null }) }));
  await expect(getSessions({ channel: "telegram", status: "failed" })).resolves.toMatchObject({ items: [{ id: "s-1" }] });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm run test -- src/lib/api/sessions.test.ts`

Expected: FAIL because the session client exports do not exist.

- [ ] **Step 3: Implement schemas and client**

Add Zod schemas for `SessionSummary`, `SessionDetail`, and messages with `direction: z.enum(["inbound", "outbound"])`, `content`, nullable `trace_id`, and nullable `error`. Implement `/api/sessions`, `/api/sessions/:id`, and `/api/sessions/:id/messages` clients. Serialize only defined channel/query/from/to/status/cursor values. All list replies must validate `{ items, next_cursor }`.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend && npm run typecheck && npm run test -- src/lib/api/sessions.test.ts src/lib/api/client.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/lib/api/schemas.ts frontend/src/lib/api/client.ts frontend/src/lib/api/sessions.test.ts && git commit -m "feat: add session API client"`

### Task 3: 实现会话调查工作台

**Files:**
- Create: `frontend/src/features/sessions/session-filters.tsx`
- Create: `frontend/src/features/sessions/session-list.tsx`
- Create: `frontend/src/features/sessions/message-timeline.tsx`
- Create: `frontend/src/features/sessions/session-workspace.tsx`
- Modify: `frontend/src/app/sessions/page.tsx`
- Test: `frontend/src/features/sessions/session-workspace.test.tsx`

**Interfaces:** Consumes Task 2 and existing `getTrace(traceId)`. Produces URL-synced filters, paged list, full message timeline, and associated Trace detail.

- [ ] **Step 1: Write the failing interaction test**

```tsx
it("点击带 trace_id 的对话消息会显示关联 Trace", async () => {
  render(<SessionWorkspace initialSessions={[session]} />);
  await userEvent.click(screen.getByRole("button", { name: /查看 Trace trace-1/ }));
  expect(await screen.findByText("Trace 详情")).toBeVisible();
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm run test -- src/features/sessions/session-workspace.test.tsx`

Expected: FAIL because `SessionWorkspace` does not exist.

- [ ] **Step 3: Implement read-only sessions**

Use query keys `['sessions', filters]`, `['messages', sessionId, cursor]` and `['trace', traceId]`; refresh session data every 30 seconds. Sync channel/query/from/to/status to `URLSearchParams`. Show textual inbound/outbound labels, message time and complete `content`; show a Trace button only when `trace_id` exists. Show “加载更多” only when a cursor exists. Implement separate loading, empty, 403 “无权查看完整对话”, and network-error views. Do not write message text to browser storage.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend && npm run lint && npm run typecheck && npm run test -- src/features/sessions/session-workspace.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add frontend/src/features/sessions frontend/src/app/sessions/page.tsx && git commit -m "feat: add session investigation workspace"`

### Task 4: 组织运行日志和验证联调

**Files:**
- Create: `frontend/src/features/logs/log-workspace.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/logs/page.tsx`
- Modify: `frontend/src/components/event-timeline.tsx`
- Modify: `frontend/README.md`
- Test: `frontend/src/features/logs/log-workspace.test.tsx`

**Interfaces:** Consumes `getEvents()`, `getTraces()`, `getTrace()`. Produces `/logs` investigation view and a compact `/` summary.

- [ ] **Step 1: Write the failing log test**

```tsx
it("点击事件会打开其关联 Trace", async () => {
  render(<LogWorkspace events={[eventWithTrace]} />);
  await userEvent.click(screen.getByRole("button", { name: /回合已提交/ }));
  expect(screen.getByText("trace-1")).toBeVisible();
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend && npm run test -- src/features/logs/log-workspace.test.tsx`

Expected: FAIL because `LogWorkspace` does not exist.

- [ ] **Step 3: Implement log page and documentation**

Move full event/Trace investigation from `/` to `/logs`; keep `/` as trace count, event count, latest refresh and links to sessions/logs. Continue 30-second REST refresh. Document `ADMIN_API_BASE_URL`, session endpoint prerequisites and manual flow: open `/sessions`, filter, open a conversation, click Trace, then open `/logs` and check the same Trace.

- [ ] **Step 4: Run full verification**

Run: `cd frontend && npm run lint && npm run typecheck && npm run test && npm run build`

Expected: PASS; manually verify the documented flow when session endpoints are available.

- [ ] **Step 5: Commit**

Run: `git add frontend && git commit -m "feat: complete session-first console"`
