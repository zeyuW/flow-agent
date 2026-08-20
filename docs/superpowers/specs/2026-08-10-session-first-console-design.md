# Flow Agent 会话优先控制台设计

## 目标

将 Web 控制台从以 Trace 为首页的技术视图调整为以会话为主入口的管理员工作台。管理员能够按用户、时间、渠道和失败状态定位 Telegram 会话，阅读完整收发对话，并从任意消息进入关联 Trace。Trace 与运行事件统一归入运行日志，用于技术调查。

首版仅提供只读调查能力，不提供人工回复、会话暂停、导出或重试。

## 导航与页面

左侧导航按管理任务分组：

```text
概览

调查
  会话与回合
  运行日志

运行
  投递记录
  自动化与主动策略
  渠道

知识与扩展
  记忆
  扩展

系统
  审计日志
  设置与权限
```

概览呈现活跃会话、失败回合、渠道健康与近期异常。会话与回合页为日常入口：会话列表默认按最后活动时间倒序，支持渠道、用户关键词、时间范围和失败状态筛选。选中会话后显示完整 Telegram 收发对话；每条消息标注方向、时间、正文与关联 `trace_id`。点击 `trace_id` 打开 Trace 详情。

运行日志页展示事件和 Trace 列表，支持按时间与 Trace 筛选；它服务于技术排障，不再作为首页主内容。

桌面端用右侧详情栏展示 Trace；窄屏把同一详情嵌入内容区，保证可读性。

## API 合同与数据流

后端新增并维护以下稳定 DTO：

```text
GET /api/sessions?channel=telegram&query=&from=&to=&status=&cursor=
GET /api/sessions/{session_id}
GET /api/sessions/{session_id}/messages?cursor=
GET /api/traces/{trace_id}
GET /api/events?trace_id=&from=&to=
```

会话、消息、事件和 Trace 的列表端点统一返回 `{ items, next_cursor }`。消息 DTO 至少包含 `id`、`direction`、`at`、`content`、`trace_id` 和可选错误摘要；会话 DTO 至少包含渠道、用户展示名、脱敏用户标识、最后活动时间、状态和最近消息摘要。

现有 `/api/events`、`/api/traces` 和 `/api/traces/{trace_id}` 继续支持运行日志。当前后端是 REST 快照接口，前端使用 30 秒轮询并显示最近刷新时间；不把它伪装为 AI 聊天式 SSE。将来后端提供真实增量事件流时，才能选择性接入 SSE。

Next.js 通过服务端 `ADMIN_API_BASE_URL` 同源代理 `/api/*` 请求，避免浏览器 CORS；浏览器不读取 API key、Token 或服务端密钥。

## 权限、安全与审计

完整 Telegram 正文仅向管理员角色返回。后端必须对正文访问写入审计记录，至少包括操作者、时间、目标会话和结果。前端不把正文写入 localStorage、sessionStorage 或 URL；不渲染 API key、Token、原始 metadata 与不受信任扩展内容。

前端对无权限、加载、空列表与请求失败分别呈现。正文未授权时显示无权限状态，而非误报为空会话。

## 前端结构与测试

新增 `features/sessions`（筛选、会话列表、对话时间线、Trace 关联）和 `features/logs`（事件/Trace 筛选与详情）。共享组件包括状态标签、分页列表、Trace 详情抽屉和时间线。

测试覆盖：筛选参数与 URL 同步、列表分页、消息方向与正文、点击 Trace、加载/空/无权限/失败状态、窄屏详情，以及敏感字段不进入页面。联调验证确认同源代理、真实 DTO 校验与 30 秒轮询。

## 非目标

本期不实现人工回复、暂停或删除会话、消息导出、投递重试、策略编辑、记忆编辑、扩展管理或浏览器内加载不受信任 Plugin。
