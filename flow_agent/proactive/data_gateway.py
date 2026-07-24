"""主动数据网关，负责隔离并标准化外部数据源。"""

import asyncio
import json
import logging
import hashlib
from pathlib import Path
from typing import Any

from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.models import DataItem, GatewayResult
from flow_agent.proactive.sources import LocalFileSource, ProactiveSource

logger = logging.getLogger(__name__)


class DataGateway:
    """每轮只调用一次已注册数据源，并按声明通道分发结果。"""

    def __init__(
        self,
        pool: McpClientPool,
        proactive_sources: list | None = None,
        local_source_file: Path | None = None,
        local_sources: list[ProactiveSource] | None = None,
    ) -> None:
        self._pool = pool
        self._content_store: dict[str, str] = {}
        self._proactive_sources = list(proactive_sources or [])
        self._local_sources = list(local_sources or [])
        self._local_source_file = local_source_file
        if local_source_file is not None:
            self._local_sources.append(LocalFileSource(local_source_file))

        self._channel_servers: dict[str, list[str]] = {
            "alert": [],
            "content": [],
            "context": [],
        }
        for source in self._proactive_sources:
            for channel in source.spec.channels:
                if channel in self._channel_servers:
                    self._channel_servers[channel].append(source.spec.server)

    async def run(self) -> GatewayResult:
        """并行采集已注册数据源，并隔离单个数据源失败。"""

        result = GatewayResult()
        self._run_errors: list[str] = []
        if self._proactive_sources:
            fetched = await asyncio.gather(
                *[
                    self._call_source(
                        source.spec.server,
                        source.spec.fetch_tool,
                    )
                    for source in self._proactive_sources
                ],
                return_exceptions=True,
            )
            for source, raw_items in zip(self._proactive_sources, fetched):
                if isinstance(raw_items, BaseException):
                    logger.warning(
                        "主动数据源采集失败: source=%s error=%s",
                        source.source_key,
                        raw_items,
                    )
                    continue
                items = self._normalize(raw_items, source.source_key)
                for channel in source.spec.channels:
                    target = getattr(result, channel, None)
                    if isinstance(target, list):
                        target.extend(items)

        result.content.extend(self._fetch_all_local_content())
        result.errors.extend(self._run_errors)
        return result

    def _fetch_local_content(self) -> list[DataItem]:
        """读取显式配置的本地数据文件。"""

        if self._local_source_file is None or not self._local_source_file.exists():
            return []
        records = LocalFileSource(self._local_source_file).fetch_records()
        return [
            DataItem(
                source=record.source,
                item_id=record.dedup_key,
                title=record.title,
                summary=record.summary,
                content=record.content,
                priority_hint=record.priority_hint,
            )
            for record in records
        ]

    def _fetch_all_local_content(self) -> list[DataItem]:
        """读取全部本地数据源，并隔离单个来源失败。"""

        records = []
        for source in self._local_sources:
            try:
                records.extend(source.fetch_records())
            except Exception as exc:
                logger.exception("本地主动数据源采集失败: source=%s", source.name)
                self._run_errors.append(f"local:{source.name}: {exc}")
        return [
            DataItem(
                source=record.source,
                item_id=record.dedup_key,
                title=record.title,
                summary=record.summary,
                content=record.content,
                priority_hint=record.priority_hint,
            )
            for record in records
        ]
    async def _call_source(self, server: str, tool: str) -> list[Any]:
        """调用单个数据源并提取 MCP 内容块。"""

        try:
            response = await self._pool.call(server, tool)
        except Exception as exc:
            logger.exception("主动数据源调用失败: server=%s tool=%s", server, tool)
            self._run_errors.append(f"mcp:{server}/{tool}: {exc}")
            return []
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, str):
            return [response]
        if not isinstance(response, dict):
            return []
        result = response.get("result", response)
        if isinstance(result, dict):
            content = result.get("content", [])
            if isinstance(content, list):
                return [
                    block.get("text", block) if isinstance(block, dict) else block
                    for block in content
                ]
        return [result]

    def _normalize(self, raw_items: list[Any], source: str) -> list[DataItem]:
        """把字符串、对象或对象数组统一转换为 DataItem。"""

        decoded: list[dict[str, Any]] = []
        for raw in raw_items:
            value: Any = raw
            if isinstance(raw, str):
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue
            if isinstance(value, list):
                decoded.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                nested_items = value.get("items")
                if isinstance(nested_items, list):
                    decoded.extend(
                        item for item in nested_items if isinstance(item, dict)
                    )
                    provider_errors = value.get("provider_errors")
                    if isinstance(provider_errors, list) and provider_errors:
                        logger.warning(
                            "主动新闻源部分降级: source=%s errors=%s",
                            source,
                            provider_errors,
                        )
                else:
                    decoded.append(value)

        items: list[DataItem] = []
        for value in decoded:
            url = str(value.get("url") or value.get("link") or "").strip()
            item_id = str(value.get("event_id") or value.get("id") or url).strip()
            title = str(value.get("title") or "").strip()
            content = str(value.get("content") or value.get("body") or "").strip()
            summary = str(value.get("summary") or "").strip()
            if not item_id and title:
                item_id = hashlib.sha256(
                    f"{source}:{title}".encode("utf-8")
                ).hexdigest()[:24]
            if url:
                content = f"{content or summary}\n{url}".strip()
            if not item_id and not title and not content and not summary:
                continue
            items.append(
                DataItem(
                    source=str(value.get("source") or source),
                    item_id=item_id,
                    title=title,
                    source_key=source,
                    summary=summary,
                    content=content,
                    ack_server=str(value.get("ack_server") or ""),
                    priority_hint=float(value.get("priority") or 0.0),
                )
            )
        return items

    async def _fetch_body(self, item: DataItem) -> str:
        """按需获取条目正文，并缓存成功结果。"""

        if item.content:
            return item.content
        if item.item_id in self._content_store:
            return self._content_store[item.item_id]
        try:
            body = await self._pool.call(
                "content_source",
                "web_fetch",
                {"url": item.summary},
            )
        except Exception:
            logger.exception("主动条目正文获取失败: item_id=%s", item.item_id)
            return ""
        text = body if isinstance(body, str) else ""
        if text:
            self._content_store[item.item_id] = text
        return text
