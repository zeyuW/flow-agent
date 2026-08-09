# Telegram 多模态能力：需求文档

- 状态：已批准
- 创建日期：2026-07-27

## 目标

用户可在 Telegram 发送图片或图片文档并获得视觉模型回答；Agent、MCP 与 Skill 可产生受控图片产物并发送给同一 Telegram 会话。

## 范围

- Telegram `photo` 与图片 `document` 的下载、校验和入站附件保存。
- 被动回合将图片附件编码为 OpenAI 兼容多模态 `image_url` 内容块，支持配置 Qwen VL 模型。
- 安全图片产物服务和 Telegram `sendPhoto` multipart 投递。
- MCP 与 Skill 对图片输入/输出的声明和统一工具契约。

## 约束

- 只接受 JPEG、PNG、WEBP、GIF；每个入站文件不超过 20 MB，单消息最多 4 张。
- 不信任 Telegram 文件名、MIME 或任意本地路径；所有文件必须位于工作区附件目录。
- 用户未配置视觉模型时，有图片的回合必须给出明确错误，不能忽略图片。
- 图片生成模型作为独立工具，不改变聊天模型接口。
- 规格文档不提交、不推送。

## 验收标准

- [x] Telegram 图片和图片文档会下载为安全附件并进入 `InboundMessage.media`。
- [x] 图片回合向视觉模型发送 text + `image_url` 内容块；纯文本保持原行为。
- [x] Agent 可通过现有 `message_push` 工具将本地图片发送到 Telegram。
- [x] Skill 可声明需要视觉模型或图片输出能力；MCP 可复用 `message_push` 的图片发送入口。
- [x] `bash scripts/verify.sh` 通过（234 项）。
