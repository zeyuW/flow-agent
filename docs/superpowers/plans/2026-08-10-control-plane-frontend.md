# Flow Agent 控制台前端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `frontend/` 建立可独立运行的 P0 只读运维控制台，安全消费 `/api/v1/admin` 的概览、渠道、事件/追踪、投递和任务数据。

**Architecture:** Next.js App Router 负责路由与布局；每个业务功能只通过 `lib/api` 提供的 Zod 校验请求函数与 TanStack Query hook 获得数据。SSE 客户端集中放在 `lib/realtime`，按资源更新查询缓存；页面不解析 HTTP 响应、不保存 API Key，也不显示敏感字段。

**Tech Stack:** Next.js、React、TypeScript（strict）、Tailwind CSS、TanStack Query、Zod、Vitest + Testing Library、Playwright。

## 全局约束

- 前端只使用 `NEXT_PUBLIC_ADMIN_API_BASE_URL` 作为服务地址，缺省为同源 `/api/v1/admin`。
- P0 严格只读；不得出现重试、暂停、恢复或任何写操作按钮。
- 所有列表消费 `{ items, next_cursor }`；绝不渲染消息正文、原始 metadata、密钥或完整会话标识。
- 页面需区分加载、空、无权、请求失败、无效响应与实时数据过期状态。
- 桌面端使用左导航、顶部状态与主内容；窄屏退化为单栏。组件必须键盘可达。
- 根 README、Docker、Compose 和文档索引不在此计划的修改范围内。

---

## 文件结构

```text
frontend/
  package.json                    # 运行、检查、单测、E2E 与构建脚本
  next.config.ts                  # Next.js 配置
  tsconfig.json                   # 严格 TypeScript 与路径别名
  vitest.config.ts                # jsdom 单测配置
  playwright.config.ts            # 浏览器验收配置
  README.md                       # 前端本地开发与环境变量说明
  src/app/                        # 根布局与页面路由
  src/components/                 # Shell、状态标签、状态面板、数据表与 Trace 抽屉
  src/features/                   # dashboard、channels、events、deliveries、automation
  src/lib/api/                    # DTO schema、请求客户端、query hook
  src/lib/realtime/               # SSE 生命周期与缓存更新
  src/styles/globals.css          # 设计令牌、主题与全局样式
  src/test/                       # Vitest 安装与 API mock
  e2e/                            # Playwright 流程测试
```

### Task 1: 初始化前端工程与应用壳

**Files:**
- Create: `frontend/package.json`, `frontend/next.config.ts`, `frontend/tsconfig.json`, `frontend/vitest.config.ts`, `frontend/playwright.config.ts`
- Create: `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/src/app/providers.tsx`, `frontend/src/styles/globals.css`
- Create: `frontend/src/components/app-shell.tsx`, `frontend/src/components/status-badge.tsx`, `frontend/src/test/setup.ts`
- Test: `frontend/src/components/status-badge.test.tsx`

**Interfaces:**
- Produces `StatusBadge({ status: HealthStatus }): JSX.Element`，其中 `HealthStatus = "healthy" | "degraded" | "stopped" | "failed" | "unknown"`。
- Produces `AppShell({ children }: PropsWithChildren)`，供所有路由共享导航与顶部栏。

- [ ] **Step 1: 写失败的状态标签组件测试**

```tsx
it("显示 unknown 的中文状态", () => {
  render(<StatusBadge status="unknown" />)
  expect(screen.getByText("状态未知")).toBeVisible()
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- status-badge.test.tsx`
Expected: FAIL，因为工程与模块尚不存在。

- [ ] **Step 3: 建立严格 TypeScript、主题令牌与应用壳**

```tsx
export function StatusBadge({ status }: { status: HealthStatus }) {
  return <span data-status={status}>{STATUS_LABEL[status]}</span>
}
```

在 `providers.tsx` 创建单个 `QueryClientProvider`；`layout.tsx` 引入全局样式并用 `AppShell` 包裹内容。`app-shell.tsx` 生成到概览、渠道、事件、投递、自动化的语义导航链接。全局样式定义暖白/深石墨、青绿色主色与成功/警告/失败色，使用 CSS 变量支持 `prefers-color-scheme`。

- [ ] **Step 4: 验证壳组件与工程脚本**

Run: `cd frontend && npm run test -- status-badge.test.tsx && npm run typecheck`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend
git commit -m "feat: scaffold control plane frontend"
```

### Task 2: 实现安全且类型化的管理 API 客户端

**Files:**
- Create: `frontend/src/lib/api/schemas.ts`, `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/queries.ts`
- Create: `frontend/src/lib/api/client.test.ts`
- Create: `frontend/src/test/handlers.ts`

**Interfaces:**
- Produces `getOverview(): Promise<OverviewDto>`、`getChannels(): Promise<Page<ChannelDto>>`、`getEvents(filters): Promise<Page<EventDto>>`、`getTrace(traceId): Promise<TraceDto>`、`getDeliveries(filters): Promise<Page<DeliveryDto>>`、`getJobs(): Promise<Page<JobDto>>`。
- Produces `AdminApiError`，其 `kind` 为 `unauthorized | forbidden | unavailable | invalid_response`。

- [ ] **Step 1: 写无效 DTO 被拒绝的失败测试**

```tsx
it("拒绝包含未定义状态的概览响应", async () => {
  server.use(http.get("/api/v1/admin/overview", () => HttpResponse.json({ health: "raw" })))
  await expect(getOverview()).rejects.toMatchObject({ kind: "invalid_response" })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- client.test.ts`
Expected: FAIL，因为 `getOverview` 尚不存在。

- [ ] **Step 3: 定义 Zod schema 与请求函数**

```ts
export const pageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), next_cursor: z.string().nullable() })

export async function getOverview(): Promise<OverviewDto> {
  return request("/overview", overviewSchema)
}
```

在 `request` 中仅设置 `Accept: application/json`，不读取或持久化 Key；以 `NEXT_PUBLIC_ADMIN_API_BASE_URL ?? "/api/v1/admin"` 组装 URL。把 HTTP 401、403、网络/5xx 与 Zod 失败映射为 `AdminApiError`。`queries.ts` 为每一项提供稳定 query key 与 `useQuery` hook。

- [ ] **Step 4: 验证安全数据层**

Run: `cd frontend && npm run test -- client.test.ts && npm run typecheck`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib frontend/src/test
git commit -m "feat: add typed admin API client"
```

### Task 3: 实现实时新鲜度状态

**Files:**
- Create: `frontend/src/lib/realtime/admin-stream.ts`, `frontend/src/lib/realtime/use-admin-stream.ts`
- Create: `frontend/src/components/freshness-indicator.tsx`
- Test: `frontend/src/lib/realtime/use-admin-stream.test.tsx`, `frontend/src/components/freshness-indicator.test.tsx`

**Interfaces:**
- Consumes SSE `{ resource, payload, occurred_at }` 与 Task 2 的 query keys。
- Produces `useAdminStream(): { isLive: boolean; isStale: boolean; lastUpdatedAt: Date | null }`。

- [ ] **Step 1: 写断线后显示过期提示的失败测试**

```tsx
it("连接发生错误时标记为过期", async () => {
  render(<FreshnessIndicator state={{ isLive: false, isStale: true, lastUpdatedAt: null }} />)
  expect(screen.getByText("数据可能已过期")).toBeVisible()
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- freshness-indicator.test.tsx`
Expected: FAIL，因为新鲜度组件尚不存在。

- [ ] **Step 3: 实现集中 SSE 连接与轮询降级状态**

```ts
source.onmessage = (event) => {
  const update = streamEventSchema.parse(JSON.parse(event.data))
  queryClient.setQueryData(queryKeyFor(update.resource), update.payload)
}
source.onerror = () => setState((value) => ({ ...value, isLive: false, isStale: true }))
```

由根 `providers.tsx` 挂载 hook。事件格式非法时丢弃该事件并维持最后安全快照；断线后关闭 `EventSource`，触发已有 query 每 30 秒刷新，重连时恢复实时状态。`FreshnessIndicator` 用可见文字和 `aria-live="polite"` 传达状态。

- [ ] **Step 4: 验证实时状态**

Run: `cd frontend && npm run test -- use-admin-stream.test.tsx freshness-indicator.test.tsx`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib/realtime frontend/src/components frontend/src/app/providers.tsx
git commit -m "feat: show control plane data freshness"
```

### Task 4: 实现概览与渠道只读页面

**Files:**
- Create: `frontend/src/app/channels/page.tsx`
- Create: `frontend/src/features/dashboard/dashboard-page.tsx`, `frontend/src/features/channels/channels-page.tsx`
- Create: `frontend/src/components/query-state.tsx`, `frontend/src/components/data-table.tsx`
- Test: `frontend/src/features/dashboard/dashboard-page.test.tsx`, `frontend/src/features/channels/channels-page.test.tsx`

**Interfaces:**
- Consumes `useOverviewQuery()` 与 `useChannelsQuery()`。
- Produces可复用 `QueryState`，为加载、空、无权、不可用、无效响应提供互斥视图。

- [ ] **Step 1: 写概览健康卡与渠道空状态的失败测试**

```tsx
it("展示运行健康与失败投递数", async () => {
  render(<DashboardPage />)
  expect(await screen.findByText("失败投递")).toBeVisible()
})
```

```tsx
it("无渠道时展示空状态", async () => {
  render(<ChannelsPage />)
  expect(await screen.findByText("暂无渠道状态")).toBeVisible()
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- dashboard-page.test.tsx channels-page.test.tsx`
Expected: FAIL，因为页面组件尚不存在。

- [ ] **Step 3: 实现概览指标、事件摘要与渠道表格**

概览展示健康度、活跃会话、队列积压、今日任务/消息与失败投递；渠道表格仅显示 `name`、`status`、`updated_at`、`error_summary`。表格列使用 `<th scope="col">`，状态使用 `StatusBadge`，不得提供控制按钮。

- [ ] **Step 4: 验证页面状态**

Run: `cd frontend && npm run test -- dashboard-page.test.tsx channels-page.test.tsx && npm run lint`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/app frontend/src/features frontend/src/components
git commit -m "feat: add overview and channel pages"
```

### Task 5: 实现事件/追踪、投递与自动化页面

**Files:**
- Create: `frontend/src/app/events/page.tsx`, `frontend/src/app/deliveries/page.tsx`, `frontend/src/app/automation/page.tsx`
- Create: `frontend/src/features/events/events-page.tsx`, `frontend/src/features/events/trace-drawer.tsx`
- Create: `frontend/src/features/deliveries/deliveries-page.tsx`, `frontend/src/features/automation/automation-page.tsx`
- Test: `frontend/src/features/events/trace-drawer.test.tsx`, `frontend/src/features/deliveries/deliveries-page.test.tsx`, `frontend/src/features/automation/automation-page.test.tsx`

**Interfaces:**
- Consumes `useEventsQuery(filters)`、`useTraceQuery(traceId)`、`useDeliveriesQuery(filters)`、`useJobsQuery()`。
- Produces `TraceDrawer({ traceId, onClose })`，使用对话框语义与关闭后焦点归还。

- [ ] **Step 1: 写投递安全性与 Trace 抽屉的失败测试**

```tsx
it("未知投递不展示重试操作", async () => {
  render(<DeliveriesPage />)
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()
})
```

```tsx
it("打开 Trace 后展示安全事件摘要", async () => {
  render(<TraceDrawer traceId="trace_123" onClose={vi.fn()} />)
  expect(await screen.findByText("工具调用完成")).toBeVisible()
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- trace-drawer.test.tsx deliveries-page.test.tsx automation-page.test.tsx`
Expected: FAIL，因为功能组件尚不存在。

- [ ] **Step 3: 实现筛选表格、Trace 时间线与任务列表**

事件和投递筛选使用 URL 查询参数 `channel`、`status`、`trace_id`、`from`、`to`；点击事件的 `trace_id` 打开抽屉并读取 `/traces/{trace_id}`。投递只展示脱敏会话 ID、状态、尝试数、时间、错误摘要与 `trace_id`。自动化只展示名称、类型、状态、下次运行、最近结果与关联追踪链接。所有 `trace_id` 提供复制按钮和可见成功反馈。

- [ ] **Step 4: 验证所有 P0 功能组件**

Run: `cd frontend && npm run test -- trace-drawer.test.tsx deliveries-page.test.tsx automation-page.test.tsx && npm run typecheck`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/app frontend/src/features
git commit -m "feat: add control plane investigation pages"
```

### Task 6: 编写文档并完成浏览器验收

**Files:**
- Create: `frontend/README.md`, `frontend/e2e/dashboard.spec.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- README 说明 `npm install`、`npm run dev`、`npm run lint`、`npm run typecheck`、`npm run test`、`npm run build`、`npm run e2e` 与 `NEXT_PUBLIC_ADMIN_API_BASE_URL`。

- [ ] **Step 1: 写窄屏概览可读取的失败 E2E 测试**

```ts
test("窄屏仍可查看运行健康", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "运行概览" })).toBeVisible()
})
```

- [ ] **Step 2: 运行 E2E 确认失败**

Run: `cd frontend && npm run e2e -- dashboard.spec.ts`
Expected: FAIL，因为 Playwright 配置及页面尚未完整可运行。

- [ ] **Step 3: 配置浏览器测试并写前端 README**

README 只描述前端目录的开发、构建、测试和环境变量；明确 API Key 不属于 `NEXT_PUBLIC_*` 环境变量、不得在浏览器保存。配置 Playwright 启动 `npm run dev` 并以 API mock/测试服务器提供安全 fixture。

- [ ] **Step 4: 运行完整前端验证**

Run: `cd frontend && npm run lint && npm run typecheck && npm run test && npm run build && npm run e2e`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add frontend
git commit -m "test: verify control plane frontend"
```

## 自检

- 概览、渠道、事件/追踪、投递、自动化分别有对应 REST DTO 和 SSE 资源。
- 请求客户端集中进行 Zod 校验与错误映射，功能组件不接触 URL 或认证细节。
- 全部 P0 页面为只读，且测试明确保证未知投递没有重试按钮。
- 每项用户可见状态都有加载、空、权限、不可用或过期处理。
