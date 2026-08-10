# 前端追踪 API 后端设计

## 范围

实现只读的本地管理 API：`GET /api/traces`、`GET /api/traces/{trace_id}` 和
`GET /api/events`。API 读取 `.flow/logs/trace.jsonl` 的历史事件；不提供认证、
写操作、SSE、WebSocket 或游标分页。

## 架构

在 `application/tracing/` 新增历史追踪查询服务。该服务以配置中的
`observe.trace_path` 为输入，容错读取 JSON Lines，并将同一 `trace_id` 的事件聚合为
回合摘要与详情。它只产生白名单化的 DTO，不暴露原始事件字典。

在 `interfaces/admin/` 新增 Pydantic 响应模型和 FastAPI 路由工厂。路由只依赖查询服务，
负责 HTTP 参数验证与 404 转换；不读取文件、SQLite 或运行时内部对象。

`bootstrap` 负责创建查询服务和 FastAPI 应用，并在独立的本地管理 HTTP 服务中挂载路由。
默认仅绑定 `127.0.0.1`，配置应允许指定端口和关闭该服务。

## 历史事件映射

被动回合事件继续写入既有 JSONL。回合的 `turn_start`、`turn_end`、`turn_error` 和
`turn_perf` 必须带有 `trace_id`、`session_id` 与 `channel`；其中 `session_id` 仅供内部聚合，
不得出现在 API 响应。

查询服务按以下规则生成数据：

- `turn_start` 创建回合，记录渠道和开始时间。
- `turn_end` 或 `turn_error` 确定完成或失败状态与结束时间。
- `turn_perf.full_reply_latency_ms` 生成整数毫秒耗时；缺失时以开始和结束时间差计算；仍无法
  计算时为 `null`。
- 与该 `trace_id` 相关的事件生成时间线；时间线按 `at` 升序，跨回合事件按 `at` 倒序。
- 没有开始事件但存在带 `trace_id` 的历史事件时，仍以 `unknown` 状态形成可查询回合，避免
  丢失旧数据。

## 脱敏与摘要

查询服务只读取事件类型、时间、trace 标识、渠道、阶段、延迟和错误类型。输出摘要由事件
类型映射为固定中文文本，例如 `turn_start` 为“回合开始”、`tool_finished` 为“工具调用完成”。
错误信息仅使用受长度限制的异常类型或预定义通用描述，绝不返回 `user_input`、
`assistant_output`、`tool_trace`、工具参数、Token、原始 metadata 或完整 session 标识。

## HTTP 契约与错误处理

三个接口的字段、状态集合、排序和默认 `limit=20` 与
`2026-08-10-frontend-tracing-api.md` 保持一致。`limit` 限制为 1–100；不在状态集合中的
`status` 返回 422。不存在的回合返回 404，响应体为 `{"detail": "追踪回合不存在"}`。
不存在、空文件、单行损坏或字段缺失的历史记录不会使接口失败：查询服务忽略损坏行并返回
可用记录或空列表。

## 测试

单元测试覆盖 JSONL 解析、回合聚合、排序、筛选、损坏数据容错和脱敏。接口测试通过
FastAPI 的测试客户端覆盖三个路由、参数校验、404 和响应模型。还应覆盖管线写入 `channel`
字段，保证新生成的历史记录可完成渠道筛选。
