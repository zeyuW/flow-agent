"""FlowAgent MCP 模块：声明式外部工具集成。

McpServerSpec     — 工作区或插件提供的服务声明
McpClient         — stdio 常驻子进程与 JSON-RPC 通信
McpServerRegistry — 原子代际发布、热重载和生命周期管理
McpToolWrapper    — 将远端工具适配为内部 Tool 协议

内置 MCP 随 Agent 发布；用户外部 MCP 位于 .flow/mcp.json；插件通过 mcp_servers() 声明能力。

兼容：
- MCPClient（旧版） — 保留向后兼容的 in-process client（client.py）
- MCPRegistry（旧版） — 保留向后兼容（registry.py）
- MCPToolAdapter（旧版） — 保留向后兼容（tool_adapter.py）
"""
