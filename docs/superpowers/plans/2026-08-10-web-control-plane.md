# Flow Agent Web 控制台实施计划

> 面向智能体执行者：必须使用 superpowers:executing-plans 按任务逐项实施，步骤使用复选框跟踪。

**目标：** 构建根目录 frontend/ 的 P0 运维控制台及其安全只读管理 API。

**架构：** interfaces.admin 将既有运行时、事件、outbox、渠道和任务状态映射为脱敏 DTO，再提供经认证的 REST 与 SSE。独立 Next.js 前端只消费这些契约，呈现 P0 运维工作台。

**技术栈：** Python 3.11、pytest、标准库 HTTP；Next.js、TypeScript、Tailwind CSS、shadcn/ui、TanStack Query、Zod、Vitest、Playwright。

## 全局约束

- frontend/ 与 backend/ 并列，并维护自己的 frontend/README.md。
- 最终集成前，不更新根 README、文档索引、Docker 或 Compose。
- infra 不得依赖 application；API DTO 映射位于 interfaces。
- 不返回 API key、Token、消息正文、原始 metadata 或未脱敏标识。
- P0 严格只读：失败和结果未知的投递均没有重试操作。

### 任务 1：定义并测试安全的管理读取模型

**文件：** 新建 backend/src/interfaces/admin/__init__.py、dtos.py、service.py；修改 backend/src/infra/persistence.py；新增 backend/tests/interfaces/test_admin_dtos.py 与 test_admin_service.py。

**接口：** 定义 mask_identifier、delivery_dto、event_dto、AdminReadService.overview/events/deliveries/channels/jobs，以及 SQLiteOutboxStore.list_records；记录按最新优先返回。

- [ ] **步骤 1：编写脱敏与查询的失败测试**

```python
def test_delivery_dto_masks_identifiers_and_omits_content():
    dto = delivery_dto(record)
    assert dto["session_id"] == "te…56"
    assert "text" not in dto and "metadata" not in dto
```

- [ ] **步骤 2：确认测试失败**

运行：cd backend && uv run pytest -q tests/interfaces/test_admin_dtos.py tests/interfaces/test_admin_service.py

预期：失败，因为管理模块和 list_records 尚不存在。

- [ ] **步骤 3：实现有边界的安全读取模型**

限制 limit 为 1–100；不支持的状态抛出 ValueError；概览由运行时、事件、适配器、outbox 和任务状态组成。

- [ ] **步骤 4：验证并提交**

运行同上，预期通过。提交：git commit -m "feat: add safe admin read models"。

### 任务 2：提供经认证的管理 REST 与 SSE

**文件：** 新建 backend/src/interfaces/admin/http.py；修改 backend/src/bootstrap/container.py、service_app.py；新增 backend/tests/interfaces/test_admin_api.py。

**接口：** 使用既有 APIKeyAuth 保护 GET /api/v1/admin/overview、/events、/deliveries、/channels、/jobs 和 /stream。列表返回 items 与 next_cursor；SSE 每 5 秒发送安全 snapshot。

- [ ] **步骤 1：编写失败的传输测试**

```python
def test_overview_requires_api_key(client):
    assert client.get("/api/v1/admin/overview").status_code == 401
```

- [ ] **步骤 2：确认测试失败**

运行：cd backend && uv run pytest -q tests/interfaces/test_admin_api.py

- [ ] **步骤 3：实现独立、可选启用的管理服务**

REST 使用 UTF-8 JSON；参数错误返回 400；意外错误返回通用 500；SSE 设置 text/event-stream 与 Cache-Control: no-store。不得改变入站 webhook。

- [ ] **步骤 4：验证并提交**

运行：cd backend && uv run pytest -q tests/interfaces/test_admin_api.py tests/architecture

预期：通过。提交：git commit -m "feat: expose authenticated admin APIs"。

### 任务 3：搭建独立前端与类型化数据层

**文件：** 新建 frontend/package.json、next.config.ts、tsconfig.json、src/app、src/styles、src/components、src/lib/api、src/lib/realtime 和 frontend/README.md；补充 Vitest 测试。

**接口：** StatusBadge 接受 healthy、degraded、stopped、failed、unknown；客户端提供 getOverview、getEvents、getDeliveries、getChannels、getJobs；流 Hook 返回 isLive 与 lastUpdatedAt。

- [ ] **步骤 1：编写失败的 UI 与 schema 测试**

```tsx
it("显示未知状态的文字标签", () => {
  render(<StatusBadge status="unknown" />)
  expect(screen.getByText("状态未知")).toBeVisible()
})
```

- [ ] **步骤 2：确认测试失败**

运行：cd frontend && npm run test

- [ ] **步骤 3：实现布局、设计令牌和客户端**

使用严格 TypeScript、Tailwind 和深浅主题；桌面端三栏、窄屏单栏。仅使用 NEXT_PUBLIC_ADMIN_API_BASE_URL，使用 Zod 校验响应；SSE 断开后显示过期状态并每 30 秒轮询。README 说明安装、运行、检查、测试、构建与禁止前端保存密钥。

- [ ] **步骤 4：验证并提交**

运行：cd frontend && npm run lint && npm run typecheck && npm run test && npm run build

预期：通过。提交：git commit -m "feat: scaffold control plane frontend"。

### 任务 4：实现并验证 P0 工作台页面

**文件：** 新建 dashboard、channels、events、deliveries、automation 功能目录及对应 app 路由；新增 frontend/e2e/dashboard.spec.ts 和功能测试。

**接口：** 概览展示健康度、计数、事件和过期状态；事件使用 URL 筛选及 TraceDrawer；投递只显示脱敏标识、状态、尝试次数、时间和错误；自动化展示任务/主动策略状态并链接失败投递。

- [ ] **步骤 1：编写失败的安全与过期状态测试**

```tsx
it("结果未知的投递不显示重试按钮", () => {
  render(<DeliveriesPage />, { wrapper: unknownDeliveryFixture() })
  expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()
})
```

- [ ] **步骤 2：确认测试失败**

运行：cd frontend && npm run test && npm run e2e

- [ ] **步骤 3：实现无障碍的只读页面**

实现加载、空、错误和过期状态；使用语义标题、文字状态标签、可筛选表格、焦点管理抽屉和可复制 trace ID。不得渲染配置、原始 metadata、消息正文或写操作。

- [ ] **步骤 4：完成全量验证并提交**

运行：cd backend && uv run pytest -q tests/interfaces tests/architecture && uv run pyright && cd ../frontend && npm run lint && npm run typecheck && npm run test && npm run build && npm run e2e

预期：全部通过。提交：git commit -m "feat: add Flow Agent control plane"。

## 自检

- 任务覆盖脱敏、API 契约、认证/SSE、独立前端、P0 页面、无障碍、测试和前端 README。
- P1 写操作及所有跨项目文档、Docker 更新明确不在范围内。
