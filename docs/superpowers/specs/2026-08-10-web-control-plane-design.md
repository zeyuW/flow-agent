# Flow Agent Web 控制台设计

## 目标与范围

为 Flow Agent 增加独立的 Web 控制台，服务于管理员与运维开发者。首版优先建立“发现异常、定位一次运行、受控处置”的闭环，不替代 Telegram、QQ 等终端用户渠道，也不在浏览器中执行 Agent 推理。

首版（P0）包含运行总览、会话与回合追踪、渠道状态、任务与主动策略状态、投递记录、审计日志。记忆编辑、任务编排和 Plugin/MCP 管理列为 P1。

## 信息架构与布局

桌面端采用三栏工作台：左侧固定导航，顶部全局状态条，中间为主内容；需要追踪细节时，右侧打开可折叠详情栏。

```text
顶部：服务健康度 | 当前模型 | 渠道在线数 | 未处理告警 | 当前工作区
左侧：概览 / 会话与回合 / 投递与事件 / 自动化与主动策略 /
      记忆 / 渠道 / 扩展 / 审计日志 / 设置与权限
中间：页面主要内容（表格、时间线、状态卡和筛选器）
右侧：选中对象的 trace、错误、工具调用及关联 session
```

概览页显示运行单元健康状态、活跃会话、队列积压、今日任务与消息、失败投递和近实时事件流。会话页以筛选表格列出渠道、脱敏会话标识、最后活动时间和状态；点击后展示一轮完整时间线：入站、记忆检索、模型调用、工具调用、回合提交和出站投递。投递页强调 `failed` 与 `unknown`，并展示重试次数和失败原因。

## 角色、操作与安全

定义三个角色：观察者只能查看脱敏观测数据；运维人员可暂停/恢复渠道与任务、重试明确失败的投递；管理员可管理策略、扩展与权限。

写操作必须使用确认弹窗，并写入不可修改的审计记录：操作者、时间、目标、前后值、结果及关联 `trace_id`。API key、Token、完整用户内容和敏感记忆默认不返回浏览器；会话 ID 和用户标识默认脱敏。对于结果不确定的 `unknown` 投递，禁止一键重试，要求人工确认后走专用处置流程。

## 视觉与交互

风格为“精密工作台”：暖白或深石墨底色，青绿色作为唯一主交互色；成功、警告和失败分别使用绿色、琥珀色、红色。组件以弱边框和轻层级区分，避免大面积阴影。中文优先、信息密度中高；仅 trace、ID、JSON 与日志使用等宽字体。首版同时提供深浅色主题与键盘可达的表格、筛选器和对话框。

## 前端结构

前端独立放在仓库根目录的 `frontend/`，与 `backend/` 并列。它拥有自己的依赖、构建配置、测试配置和 `frontend/README.md`；该 README 只说明前端的本地开发、构建、测试和环境变量。功能按业务边界组织，而非按页面堆叠：

```text
frontend/src/
  app/                 # 路由、根布局、认证与 Provider
  features/            # dashboard、sessions、deliveries、automation、channels、audit
  components/          # 共享 UI、数据表、状态标签、Trace 时间线
  lib/api/             # 类型、请求客户端、错误映射与 Zod schema
  lib/realtime/        # SSE 订阅、缓存更新与断线重连
  styles/              # 设计令牌与全局样式
  test/                # 单元、组件及 E2E 测试
```

先以 REST 获取初始快照，并通过 SSE 推送状态与事件增量；只有出现双向流式控制需求时才引入 WebSocket。TanStack Query 负责缓存、失效和轮询降级。

## 后端 API 边界

浏览器只访问 `interfaces` 层新增的管理 API，例如 `/api/v1/admin/health`、`/runtime`、`/sessions`、`/traces/{trace_id}`、`/deliveries`、`/jobs`、`/channels`、`/audit-events` 和 `/events`（SSE）。接口层调用 application 的查询/命令用例；不得从前端读取 SQLite、`.flow/` 或 `config.toml`，也不得让 `infra` 依赖 application。

现有 `RuntimeServiceSnapshot`、`RuntimeHealth`、`ChannelStatus`、`EventStore` 和 SQLite outbox 是首版 API 的主要数据来源。响应应提供分页、时间范围、渠道、状态和 `trace_id` 筛选，返回稳定的 DTO，而不是直接暴露领域对象。

### 前端与管理 API 对照

P0 统一使用 `/api/v1/admin`。此前 `frontend-tracing-api.md` 中的 `/api/traces`、`/api/events` 是并行开发草案，不作为本次实现的路由；其中追踪页需求并入下表的 `events` 与 `traces` 资源。所有列表统一返回 `{ "items": [...], "next_cursor": string | null }`，时间均为 UTC ISO 8601，浏览器请求携带管理员 API Key，但不得将 Key 写入源码、LocalStorage 或日志。

| 前端路由 / 功能 | 初始 REST 数据 | 实时增量 | 页面消费的安全 DTO | 后端数据归属 |
| --- | --- | --- | --- | --- |
| `/` 概览 | `GET /overview` | `GET /stream` 的 `overview` 事件 | `OverviewDto`：服务健康、活跃会话数、队列积压、今日计数、失败投递数 | `RuntimeServiceSnapshot`、运行时健康、事件与 outbox 聚合 |
| `/channels` 渠道 | `GET /channels` | `channel_changed` | `ChannelDto`：名称、状态、更新时间、脱敏错误摘要 | `ChannelStatus` 与渠道适配器运行状态 |
| `/events` 事件与回合 | `GET /events?cursor&channel&status&trace_id&from&to` | `event_created` | `EventDto`：`trace_id`、阶段、状态、时间、安全摘要、错误摘要 | `EventStore` |
| 右侧 Trace 抽屉 | `GET /traces/{trace_id}` | 无；抽屉打开时刷新 | `TraceDto`：回合状态、阶段时间线、工具安全摘要、关联投递摘要 | 按 `trace_id` 查询的 EventStore 与 outbox |
| `/deliveries` 投递 | `GET /deliveries?cursor&status&channel&trace_id&from&to` | `delivery_changed` | `DeliveryDto`：脱敏会话标识、状态、尝试数、时间、错误摘要、`trace_id` | SQLite outbox 的安全投影 |
| `/automation` 自动化与主动策略 | `GET /jobs` | `job_changed` | `JobDto`：名称、类型、状态、下次运行、最近结果、关联 `trace_id` | 调度器与主动运行时快照 |
| 全局数据新鲜度 | 无独立请求 | SSE 连接状态 | `StreamState`：`is_live`、`last_updated_at`、`is_stale` | 浏览器 SSE 客户端；断线后 REST 轮询 |

`GET /stream` 使用 `text/event-stream`，事件 `data` 的格式为 `{ "resource": "overview|channels|events|deliveries|jobs", "payload": <对应 DTO 或 DTO 数组>, "occurred_at": "..." }`。前端按 `resource` 更新 TanStack Query 缓存；连接失败时保留最后成功快照、显示“数据可能已过期”，并以 30 秒间隔轮询当前页面的 REST 查询。SSE 仅推送已脱敏的 DTO，不推送配置、消息正文、原始 metadata、原始工具参数或密钥。

前端 `src/lib/api/` 对每个 DTO 提供 Zod schema、TypeScript 推导类型及请求函数；`src/features/<resource>/` 只调用对应 query hook，不知晓 URL、认证头或 SSE 细节。接口不可用、返回无法通过 schema 校验或返回 401/403 时，分别映射为“暂时不可用”、“数据格式异常”和“无权访问”状态，且不显示服务器原始响应。

## 错误处理与验收

页面将空状态、无权限、暂时不可用和加载失败分别呈现；SSE 断线时显示“数据可能已过期”，自动退避重连，并保留最后成功快照。危险操作失败后保留表单和服务器返回的可读错误。

P0 验收标准：

- 管理员可在一个页面确认所有运行单元与渠道的健康状态。
- 可通过会话或 `trace_id` 找到一轮处理的完整阶段、工具摘要和投递结果。
- 可筛选失败投递与失败任务，并查看其关联错误和审计记录。
- 所有写操作具备权限校验、确认交互和审计事件；敏感配置不会进入前端响应。
- 窄屏可阅读核心状态，桌面端可完成完整调查和处置流程。

## 非目标与实施顺序

首版不提供自然语言聊天、模型配置编辑器、完整日志检索平台、直接 SQL 查询或在浏览器中加载不受信任的 Plugin。实施顺序为：先定义管理 API 与权限/审计边界，再建立前端骨架和设计令牌，随后实现概览、会话追踪、投递/任务页面，最后接入 SSE 与 P1 管理功能。

在前端全部开发、测试和验收完成前，不更新根 `README.md`、`docs/README.md`、Docker/Compose、文档索引或其他跨项目文件。最终集成阶段再一次性更新这些入口，并补充根目录前后端协作方式。
