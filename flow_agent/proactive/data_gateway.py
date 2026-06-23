"""DataGateway: parallel fetch from MCP sources (spec 3)."""

import asyncio
import logging

from flow_agent.proactive.models import DataItem, GatewayResult
from flow_agent.proactive.mcp_pool import McpClientPool

logger = logging.getLogger(__name__)


class DataGateway:
    """Parallel data fetch from MCP alert/content/context sources (spec 3b-3e)."""

    def __init__(self, pool: McpClientPool) -> None:
        self._pool = pool
        self._content_store: dict[str, str] = {}

    async def run(self) -> GatewayResult:
        """Parallel fetch three data streams (spec 3c)."""
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
        items = await self._call_source("alert_source", "get_proactive_alerts")
        return self._normalize(items, "alert")

    async def _fetch_content(self) -> list[DataItem]:
        items = await self._call_source("content_source", "get_proactive_events")
        normalized = self._normalize(items, "content")
        # spec 3d: parallel fetch content body
        if normalized:
            bodies = await asyncio.gather(
                *[self._fetch_body(item) for item in normalized],
                return_exceptions=True,
            )
            for item, body in zip(normalized, bodies):
                if isinstance(body, str) and body:
                    item.content = body
        return normalized

    async def _fetch_context(self) -> list[DataItem]:
        items = await self._call_source("context_source", "get_proactive_context")
        return self._normalize(items, "context")

    async def _call_source(self, server: str, tool: str) -> list:
        try:
            result = await self._pool.call(server, tool)
            if result and isinstance(result, dict):
                r = result.get("result", {})
                content = r.get("content", [])
                if isinstance(content, list):
                    return [c.get("text", "{}") for c in content if isinstance(c, dict)]
            return []
        except Exception:
            logger.debug("MCP call failed: %s/%s", server, tool)
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
        """Fetch full content body (spec 3d)."""
        if item.content:
            return item.content
        try:
            return await self._pool.call("content_source", "web_fetch", {"url": item.summary})
        except Exception:
            return ""
