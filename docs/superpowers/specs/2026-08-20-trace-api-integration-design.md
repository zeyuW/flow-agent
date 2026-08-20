# Trace API 前端联调设计

## 目标与范围

本次仅完成 Web 控制台与 `flow-agent-admin-api` 已实现的只读 Trace
接口联调。浏览器通过 Next.js 的同源 `/api/*` 代理访问管理服务；不实现
会话工作台、SSE、`/api/v1/admin/*` 管理面接口或任何写操作。

稳定接口为：

- `GET /api/traces?limit=&status=&channel=`
- `GET /api/traces/{trace_id}`
- `GET /api/events?limit=&trace_id=&type=`

## 契约适配

前端 API client 继续对所有响应进行 Zod 校验，但应与后端
`interfaces.admin.schemas` 精确一致：

- Trace 摘要的 `started_at` 为可空 ISO 8601 时间；
- 详情和事件中的 `error` 为可选且可空字符串；
- `/api/events` 返回事件数组，不是 SSE；
- 列表页使用 30 秒 REST 轮询，错误时保留独立错误提示。

删除未被页面消费且无后端实现的 `runtime`、`deliveries`、`channels`、
`jobs` 与 SSE client，避免误导后续调用方。

## 前端数据流

`/` 同时读取 Trace 列表和事件列表；用户选择 Trace 后读取详情。TanStack
Query 以各端点为独立缓存键，每 30 秒重新读取快照。`ADMIN_API_BASE_URL`
仅供 Next.js rewrite 使用，绝不以 `NEXT_PUBLIC_` 暴露，也不保存正文或凭据。

## 验证

新增或更新 client contract tests，覆盖可空 `started_at`、省略 `error` 的事件
以及三个真实路径。随后运行 lint、类型检查、完整 Vitest 套件与生产构建；在
本机管理 API 启动后，以 `ADMIN_API_BASE_URL=http://127.0.0.1:8790` 完成浏览器
路径验证：Trace 列表、事件列表及详情均可读取。
