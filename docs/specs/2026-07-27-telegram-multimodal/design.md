# Telegram 多模态能力：设计方案

- 状态：已批准
- 对应需求：requirements.md

## 结构

新增附件服务负责文件名、扩展名、MIME、大小、目录边界与 data URL 编码。Telegram 渠道只解析更新、选择图片、调用 `getFile` 并交给附件服务保存。被动管道将已校验路径构建为最后一条 user 多模态消息。

图片输出统一使用 `ImageArtifact`，其中只允许安全本地路径或 HTTPS URL。`send_image` 工具、MCP 适配器和 Skill 都产生该对象；Telegram 渠道以 `sendPhoto` multipart 上传本地文件，文本作为 caption 或单独消息发送。

## 数据流

```text
Telegram update → 图片下载 → AttachmentStore → InboundMessage.media
→ PassiveTurnPipeline → Agent 多模态消息 → Qwen-VL → 文本回复

工具 / MCP / Skill → ImageArtifact → ImageArtifactStore → OutboundMessage.media
→ Telegram sendPhoto
```

## 错误语义

- 不能下载、超限或不是受支持图片：不创建入站消息，并记录不含令牌的错误。
- 视觉模型不可用：被动回合发送说明性错误回复。
- 图片发送失败：渠道返回可重试投递失败，不标记成功。
- MCP/Skill 返回不安全路径：拒绝并报告工具错误。

## 测试策略

- Telegram update 的 photo/document、大小限制、下载失败和无 caption。
- 多模态消息格式、纯文本兼容和视觉模型缺失。
- 本地图片、HTTPS 图片与目录逃逸的出站验证。
- MCP/Skill 图像声明与产物校验。
