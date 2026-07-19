"""主动消息发送前的去重和副作用规划。"""

import hashlib
import logging

from flow_agent.proactive.gate import ProactiveStateStore
from flow_agent.proactive.models import JudgeResult, ResolveResult

logger = logging.getLogger(__name__)
_DELIVERY_WINDOW = 86400.0


def resolve_decision(
    judge: JudgeResult,
    *,
    state_store: ProactiveStateStore,
    chat_id: str = "",
    mcp_pool=None,
    sources: list | None = None,
) -> ResolveResult:
    """根据评估结果、引用集合和消息内容做最终发送决策。"""

    if judge.decision == "skip" or not judge.message:
        return ResolveResult(decision="skip")

    delivery_key = _build_delivery_key(judge.cited_item_ids)
    content_key = _content_hash(judge.message)
    if state_store.was_delivered(
        delivery_key, _DELIVERY_WINDOW
    ) or state_store.was_delivered(content_key, _DELIVERY_WINDOW):
        logger.info("主动消息去重命中: key=%s", (delivery_key or content_key)[:16])
        return ResolveResult(
            decision="skip",
            delivery_key=delivery_key or content_key,
        )

    effects = _build_side_effects(
        judge.cited_item_ids,
        delivery_key,
        content_key,
        state_store,
        mcp_pool,
        sources or [],
    )
    return ResolveResult(
        decision="send",
        message=judge.message,
        cited_item_ids=judge.cited_item_ids,
        delivery_key=delivery_key or content_key,
        side_effects=effects,
    )


def _build_delivery_key(cited: list[str]) -> str:
    """根据排序后的引用集合生成稳定交付键。"""

    if not cited:
        return ""
    raw = ",".join(sorted(cited))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _content_hash(text: str) -> str:
    """根据标准化消息正文生成内容去重键。"""

    normalized = " ".join(text.split()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _build_side_effects(
    cited: list[str],
    delivery_key: str,
    content_key: str,
    store: ProactiveStateStore,
    mcp_pool=None,
    sources: list | None = None,
) -> list:
    """创建只在真实投递成功后执行的状态更新和数据源确认。"""

    effects = []

    def mark_delivery() -> None:
        store.mark_sent(delivery_key, content_key)
        logger.info("主动交付状态已记录: key=%s", (delivery_key or content_key)[:16])

    effects.append(mark_delivery)

    if cited and mcp_pool is not None and sources:

        async def ack_cited_items() -> None:
            for source in sources:
                if not source.spec.ack_tool:
                    continue
                try:
                    await mcp_pool.call(
                        source.spec.server,
                        source.spec.ack_tool,
                        {"event_ids": cited},
                    )
                except Exception:
                    logger.exception(
                        "主动数据源确认失败: source=%s",
                        source.source_key,
                    )

        effects.append(ack_cited_items)

    return effects
