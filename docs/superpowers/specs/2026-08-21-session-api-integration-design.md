# 会话 API 接入设计（第一期）

## 目标

将前端“会话”页的示例数据替换为本机 Flow Agent 服务中的历史会话数据。用户可按日期范围筛选会话、查看会话摘要，并按需查看其中的用户与 Agent 消息。

本期只接入会话数据；定时任务、技能与连接器、插件页面继续使用静态展示数据。

## 约束与原则

- 管理 API 继续仅绑定本机地址，不提供写操作。
- 会话正文只在请求单个会话详情时返回，列表接口不返回完整消息。
- 代码以清晰、直接为首要目标；不引入通用仓库层、事件溯源或额外服务进程。
- `interfaces` 不直接访问被动会话私有存储；由应用层查询服务提供数据。

## 渠道感知的会话键

新会话使用 `channel:conversation_id` 作为持久化会话键。例如：

```text
telegram:123456
qq:123456
weixin:123456
```

`channel` 来自统一入站消息，`conversation_id` 保留渠道提供的原始会话标识。渠道名不允许包含冒号；解析时只按第一个冒号分隔，因此原始会话 ID 即使包含冒号也可保留。

旧数据库中不包含冒号的键继续可读，并在 API 中标记为 `legacy` 渠道。这样无需迁移或删除历史会话，也不会让新接入的 QQ、微信等渠道与既有渠道混淆。

## 后端结构

新增 `application/passive/app/session_query.py`，提供一个仅用于读取历史会话的 `SessionQueryService`。它依赖现有 `SessionStore`，负责：

1. 按更新时间与日期范围返回会话摘要；
2. 读取单个会话的消息；
3. 将会话键拆分为渠道和外部会话 ID；
4. 过滤为前端需要的 `user`、`assistant` 消息，并保留 Agent 消息的工具链。

`SessionStore` 新增直接、有限的查询方法：列出会话摘要和读取已有会话。组合根创建 `SessionQueryService` 并注入管理路由；管理路由不直接执行 SQLite 查询。

被动消息管道在创建 `TurnFlow` 时，将统一消息的 `channel` 与 `conversation_id` 组合为新会话键。出站仍使用独立的原始 `chat_id`，不改变渠道投递目标。

## API 契约

```text
GET /api/sessions?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&limit=50
GET /api/sessions/{session_id}
```

日期按服务所在时区解释，`start_date` 和 `end_date` 为闭区间。列表默认返回最近更新的 50 条，最大 100 条。

列表项：

```json
{
  "id": "telegram:123456",
  "channel": "telegram",
  "external_conversation_id": "123456",
  "created_at": "2026-08-21T02:24:00Z",
  "updated_at": "2026-08-21T02:26:00Z",
  "message_count": 4,
  "preview": "已创建提醒。"
}
```

详情项在摘要字段之外返回按时间排序的消息：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "下午三点提醒我准备会议材料。",
      "timestamp": "2026-08-21T02:26:00Z",
      "tool_chain": []
    },
    {
      "role": "assistant",
      "content": "已创建提醒。",
      "timestamp": "2026-08-21T02:26:01Z",
      "tool_chain": ["schedule_task"]
    }
  ]
}
```

会话不存在时返回 404。无匹配日期时列表返回空数组。

## 前端接入

前端新增会话 Schema 与 API 客户端函数。会话页：

1. 日期筛选变化后请求摘要列表；
2. 选择会话后请求详情；
3. 用 `channel` 作为渠道标签，使用消息角色显示用户或 Agent 气泡；
4. 显示加载中、接口错误和空日期状态；
5. 删除当前硬编码的会话、消息和工具示例数据。

定时任务、技能与连接器、插件页面不请求后端，保持现有静态原型。

## 验证

- 后端：会话键区分渠道；旧键兼容；日期范围、限制、空结果、详情 404；消息正文与工具链的 API 契约。
- 前端：日期参数请求正确；选择会话加载详情；加载、空结果、错误状态可见；真实 API 数据正确映射到对话气泡。
- 回归：现有 Trace API 测试继续通过，完整后端与前端检查通过。
