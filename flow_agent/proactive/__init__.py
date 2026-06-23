"""Proactive message delivery system: adaptive loop with 5-stage pipeline.

ProactiveLoop       — adaptive interval loop, MCP pool, background task (spec 1)
ProactiveTurnPipeline— Gate → Fetch → Judge → Resolve → Deliver (spec 2-6)
Gate / AnyActionGate — admission: busy, cooldown, quota (spec 2)
DataGateway          — parallel fetch from MCP alert/content/context (spec 3)
JudgeLoop            — LLM tool-call loop for content classification (spec 4)
Resolve              — delivery dedup + semantic dedup (spec 5)
Deliver              — session persist + outbound dispatch (spec 6)
McpClientPool        — persistent MCP connections (spec 3e)
build_proactive_runtime — factory to assemble the full runtime (spec 1a)
"""
