# Requirements

## Goal

让被动对话中的图片 MCP 结果能够以本地图片路径或公开 HTTP(S) URL 的形式发送回当前 Telegram 会话。

## Functional requirements

- `message_push` 必须允许只发送图片，不强制要求文本。
- 被动回合调用 `message_push` 时，运行时必须覆盖模型提供的 `channel` 与 `chat_id`，始终投递到当前入站会话。
- Telegram 图片发送必须支持受控本地文件和 HTTP(S) URL；其他 URL 协议必须拒绝。
- 图片 MCP 的工具结果保持原样返回模型，由模型调用 `message_push`；不解析第三方 MCP 的私有输出格式。
- 本地图片发送的现有大小限制和错误语义保持不变。

## Non-goals

- 不实现图片搜索、下载或生成服务。
- 不为 MCP 输出引入通用媒体资产模型。
- 不修改主动推送与后台任务的消息路由。

## Acceptance criteria

- MCP 返回公开图片 URL 后，模型可调用 `message_push(image_path=...)`，Telegram 使用 `sendPhoto` 发送该 URL。
- MCP 返回本地路径后，Telegram 保持 multipart 上传行为。
- 在被动回合中，模型不能借助 `message_push` 指定其他 channel 或 chat_id。
