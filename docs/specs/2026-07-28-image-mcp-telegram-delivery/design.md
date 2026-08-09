# Design

保持 MCP 工具的通用文本返回接口。模型收到图片服务返回的公开 URL 或本地绝对路径后，调用现有 `message_push`，不在运行时猜测或解析第三方服务的结果结构。

被动管道在执行 `message_push` 前注入当前入站消息的 `channel` 与 `telegram_chat_id`，并覆盖模型传入的同名字段。这样图片只能回复给发起请求的用户。

Telegram 发送端以值的形态分支：HTTP(S) URL 通过 JSON 调用 `sendPhoto`；其他值按现有本地文件路径上传。非 HTTP(S) URL 不作为远端图片处理。

```text
图片 MCP -> URL 或本地路径 -> message_push
                               -> 当前会话身份注入
                               -> Telegram sendPhoto
```
