# 前端追踪 API 契约

> 本契约用于支持前后端并行开发。

## 目的

本文件定义 Flow Agent 前端追踪页面与后端管理 API 的最小契约。前后端可据此独立开发：前端以本文件中的示例构造 mock 数据，后端以 FastAPI 实现相同响应。首版只读，不涉及登录、权限、配置修改或任务控制。

服务默认仅绑定 `127.0.0.1`，基础路径为 `/api`。所有时间使用 ISO 8601 UTC 字符串，耗时使用整数毫秒。不得返回用户消息正文、模型完整输出、Token、工具原始参数或原始 metadata。

## 通用约定

状态固定为 `running`、`completed`、`failed`、`cancelled`、`unknown`。列表默认 `limit=20`，范围为 1–100。错误响应统一为：

```json
{"detail":"可读的错误说明"}
```

## `GET /api/traces`

返回最近的 Agent 回合摘要，用于追踪列表。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `limit` | integer | 返回数量，默认 20。 |
| `status` | string | 可选状态筛选。 |
| `channel` | string | 可选渠道筛选，例如 `telegram`。 |

```json
[
  {
    "id": "trace_123",
    "channel": "telegram",
    "status": "completed",
    "started_at": "2026-08-10T10:00:00Z",
    "duration_ms": 4210
  }
]
```

`id` 是前端跳转详情的唯一标识。首版不返回完整 `session_id`；如后续需要显示，只能返回脱敏值。

## `GET /api/traces/{trace_id}`

返回一轮 Agent 处理及其事件时间线，用于详情抽屉或详情页。未知 `trace_id` 返回 404。

```json
{
  "id": "trace_123",
  "channel": "telegram",
  "status": "completed",
  "started_at": "2026-08-10T10:00:00Z",
  "finished_at": "2026-08-10T10:00:04Z",
  "duration_ms": 4210,
  "error": null,
  "events": [
    {
      "type": "turn_started",
      "at": "2026-08-10T10:00:00Z",
      "status": "ok",
      "summary": "收到 Telegram 消息",
      "error": null
    },
    {
      "type": "tool_finished",
      "at": "2026-08-10T10:00:03Z",
      "status": "ok",
      "summary": "工具调用完成",
      "error": null
    }
  ]
}
```

`events` 按 `at` 升序排列。`summary` 是后端生成的安全摘要；失败时 `error` 提供已脱敏的可读原因。

## `GET /api/events`

返回跨回合的最新事件，用于概览页事件流和前端轮询。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `limit` | integer | 返回数量，默认 20。 |
| `trace_id` | string | 可选，限制为某次回合。 |
| `type` | string | 可选事件类型筛选。 |

```json
[
  {
    "trace_id": "trace_123",
    "type": "turn_committed",
    "at": "2026-08-10T10:00:04Z",
    "status": "ok",
    "summary": "回合已提交"
  }
]
```

结果按 `at` 倒序排列。前端每 5 秒轮询此接口；追踪列表每 10 秒轮询。当前不使用 SSE 或 WebSocket。

## 实现边界

后端在 `backend/src/interfaces/admin/` 中实现 FastAPI 路由、Pydantic schema 和查询服务；它只能通过应用层读取运行时和事件数据，不直接让浏览器访问 SQLite 或 `.flow/`。前端在 `frontend/` 中以 TypeScript 类型和 mock 数据先完成列表、详情与事件流页面。

未来加入认证、游标分页、SSE、渠道管理或任务控制时，以新增字段和新接口扩展；不改变本文件中已定义字段的含义。
