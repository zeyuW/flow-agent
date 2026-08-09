# Telegram 多模态能力：任务清单

- 状态：实施中
- 对应需求：requirements.md
- 对应设计：design.md

## 任务

### 阶段 1：图片输入和视觉理解

- [x] 为附件校验、Telegram photo/document 下载和多模态消息写失败测试。
- [x] 实现 Telegram 下载、文件签名校验和被动管道消息构造。
- [x] 验证 OpenAI 兼容视觉消息与纯文本兼容。

### 阶段 2：图片出站

- [x] 为 Telegram multipart `sendPhoto` 写失败测试。
- [x] 实现本地图片大小校验与 Telegram 图片发送。

### 阶段 3：MCP 与 Skill

- [x] 为 Skill 图像能力声明写失败测试。
- [x] 接入 Skill 图像能力声明；MCP 可通过既有 `message_push` 工具发送图片。
- [x] 运行完整 CI、隔离扫描和空白检查；不提交、不推送。
