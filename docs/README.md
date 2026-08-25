# Flow Agent 文档

## 从哪里开始

- [项目入口和快速开始](../README.md)：了解项目定位、配置和启动方式。
- [系统架构](ARCHITECTURE.md)：理解分层、消息流、生命周期和恢复边界。
- [后端开发入口](../backend/README.md)：了解源码组织、依赖方向和验证命令。
- [管理控制台与本机 API](features/control-plane.md)：了解会话、追踪、定时任务和扩展管理。
- [扩展 API](api.md)：通过 Plugin、MCP 和 Skill 扩展新功能。

## 理解系统能力

这些文档按能力解释 Flow Agent 如何工作，重点是设计思路、运行流程和边界：

- [Agent Loop](features/agent-loop.md)：共享执行内核、会话隔离和回合提交。
- [被动回复](features/passive.md)：用户消息如何经过一轮 Agent 处理后得到回复。
- [主动回复](features/proactive.md)：系统如何发现机会并在准入后主动触达。
- [后台任务](features/automation.md)：定时任务、自动化作业和委托子 Agent 的区别。
- [记忆](features/memory.md)：记忆如何产生、检索、注入和整理。
- [渠道](features/channels.md)：外部平台如何统一接入和投递消息。
- [管理控制台](features/control-plane.md)：本机 Web 控制台如何查询运行状态并执行受控管理操作。

## 开发扩展

- [扩展 API](api.md)：选择 Plugin、MCP 或 Skill，并完成自定义接入、热更新、安全检查和验证。
- [项目 Skill 说明](../skills/README.md)：项目共享 Skill 的目录约定与本机 Skill 的存放位置。

## 运行目录

后端配置文件 `config.toml` 位于仓库根目录；本机运行时默认使用用户目录 `~/.flow/`
保存数据库、记忆、日志、追踪、插件、用户 Skill、MCP 配置和后台任务记录。Docker
脚本使用项目根 `.flow/` 作为独立的容器挂载目录，具体边界见[管理控制台与本机 API](features/control-plane.md)
和根目录 [README](../README.md)。

## 追踪具体变更

- [当前架构规范](specs/README.md)：当前生效的架构边界和开发约束。
- [规格、设计和实施记录](specs/)：针对具体变更保存的需求、设计与任务记录。

## 维护文档

- [知识沉淀规则](knowledge.md)：决定什么内容应该写入 README、架构文档、功能文档或规格记录。

新增能力或改变现有行为后，先按[知识沉淀规则](knowledge.md)判断更新哪一层，再回到本索引和根 README 检查入口是否完整。
