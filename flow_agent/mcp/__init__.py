"""FlowAgent MCP 模块：Model Context Protocol 工具集成。

McpClient        — stdio 子进程 + JSON-RPC 通信（initialize/tools/list/tools/call）
McpServerRegistry — 服务器生命周期管理（add/remove/list）+ 持久化 + 后台重连
McpToolWrapper    — 将 MCP 远端工具适配为内部 Tool 协议

管理工具：
- mcp_add    — 添加并连接 MCP server
- mcp_remove — 移除 server 并清理工具
- mcp_list   — 列出已注册 servers

兼容：
- MCPClient（旧版） — 保留向后兼容的 in-process client（client.py）
- MCPRegistry（旧版） — 保留向后兼容（registry.py）
- MCPToolAdapter（旧版） — 保留向后兼容（tool_adapter.py）
"""
