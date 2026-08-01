"""主动消息投递系统：自适应循环 + 五阶段管道。

ProactiveLoop       — 自适应间隔循环，MCP 连接池，后台任务
ProactiveTurnPipeline— Gate → Fetch → Judge → Resolve → Deliver
Gate / AnyActionGate — 准入检查：忙碌、冷却、配额
DataGateway          — 从 MCP 并行获取告警/内容/上下文
JudgeLoop            — LLM 工具调用循环，用于内容分类
Resolve              — 交付去重 + 语义去重
Deliver              — 会话持久化 + 出站分发
McpClientPool        — 持久化 MCP 连接
build_proactive_runtime — 组装完整运行时的工厂
"""
