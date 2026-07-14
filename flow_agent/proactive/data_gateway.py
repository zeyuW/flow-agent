"""DataGateway: 从 MCP 数据源并行获取。"""

import asyncio
import logging
from pathlib import Path

from flow_agent.proactive.models import DataItem, GatewayResult
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.sources import LocalFileSource

logger = logging.getLogger(__name__)


class DataGateway:
    """从 MCP 告警/内容/上下文数据源并行获取数据。"""

    def __init__(self, pool: McpClientPool, proactive_sources: list = None, local_source_file: Path = None) -> None:
        self._pool = pool
        self._content_store: dict[str, str] = {}
        self._proactive_sources = proactive_sources or []
        self._local_source_file = local_source_file

        # 构建通道到 server 的映射
        self._channel_servers: dict[str, list[str]] = {
            "alert": [],
            "content": [],
            "context": [],
        }
        for source in proactive_sources:
            for channel in source.spec.channels:
                if channel in self._channel_servers:
                    self._channel_servers[channel].append(source.spec.server)

    async def run(self) -> GatewayResult:
        """并行获取三个数据流。"""
        alerts, content, context = await asyncio.gather(
            self._fetch_alerts(),
            self._fetch_content(),
            self._fetch_context(),
            return_exceptions=True,
        )
        return GatewayResult(
            alerts=alerts if isinstance(alerts, list) else [],
            content=content if isinstance(content, list) else [],
            context=context if isinstance(context, list) else [],
        )

    async def _fetch_alerts(self) -> list[DataItem]:
        """从所有声明了 alert 通道的 server 获取数据"""
        all_items = []
        for server in self._channel_servers["alert"]:
            items = await self._call_source(server, "get_proactive_alerts")
            all_items.extend(self._normalize(items, "alert"))
        return all_items

    async def _fetch_content(self) -> list[DataItem]:
        """从所有声明了 content 通道的 server 获取数据"""
        all_items = []
        for server in self._channel_servers["content"]:
            items = await self._call_source(server, "get_proactive_events")
            all_items.extend(self._normalize(items, "content"))
        
        # 从本地文件源获取数据（用于快速测试）
        if self._local_source_file and self._local_source_file.exists():
            local_source = LocalFileSource(self._local_source_file)
            records = local_source.fetch_records()
            for record in records:
                item = DataItem(
                    source=record.source,
                    item_id=record.dedup_key,
                    title=record.title,
                    summary=record.summary,
                    content=record.content,
                    priority_hint=record.priority_hint,
                )
                all_items.append(item)
            logger.info(f"从本地文件加载了 {len(records)} 条数据")
        
        return all_items

    async def _fetch_context(self) -> list[DataItem]:
        """从所有声明了 context 通道的 server 获取数据"""
        all_items = []
        for server in self._channel_servers["context"]:
            items = await self._call_source(server, "get_proactive_context")
            all_items.extend(self._normalize(items, "context"))
        return all_items

    async def _call_source(self, server: str, tool: str) -> list:
        try:
            result = await self._pool.call(server, tool)
            logger.debug("MCP call result from %s/%s: %s", server, tool, result)
            
            if result and isinstance(result, dict):
                r = result.get("result", {})
                content = r.get("content", [])
                if isinstance(content, list):
                    texts = [c.get("text", "{}") for c in content if isinstance(c, dict)]
                    logger.debug("Extracted %d text items from %s/%s", len(texts), server, tool)
                    return texts
            return []
        except Exception as e:
            logger.debug("MCP call failed: %s/%s: %s", server, tool, e)
            return []

    def _normalize(self, raw_items: list, source: str) -> list[DataItem]:
        items = []
        for raw in raw_items:
            import json
            try:
                d = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                continue
            if not isinstance(d, dict):
                continue
            items.append(DataItem(
                source=source,
                item_id=str(d.get("id", "")),
                title=str(d.get("title", "")),
                summary=str(d.get("summary", "")),
                content=str(d.get("content", "")),
                ack_server=str(d.get("ack_server", "")),
                priority_hint=float(d.get("priority", 0.0)),
            ))
        return items

    async def _fetch_body(self, item: DataItem) -> str:
        """获取完整内容主体。"""
        # 如果已经有 content，直接返回
        if item.content:
            logger.debug(f"Item {item.key} 已有 content，跳过获取")
            return item.content
        # 否则尝试从 MCP 获取
        try:
            return await self._pool.call("content_source", "web_fetch", {"url": item.summary})
        except Exception:
            logger.debug(f"获取 body 失败，返回空字符串")
            return ""
