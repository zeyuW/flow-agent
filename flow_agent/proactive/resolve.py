"""Resolve: delivery dedup + semantic dedup (spec 5)."""

import hashlib
import logging

from flow_agent.proactive.gate import ProactiveStateStore
from flow_agent.proactive.models import JudgeResult, ResolveResult

logger = logging.getLogger(__name__)
_DELIVERY_WINDOW = 300  # 5 minutes (reduced for testing)


def resolve_decision(
    judge: JudgeResult,
    *,
    state_store: ProactiveStateStore,
    chat_id: str = "",
    mcp_pool=None,
    sources: list = None,
) -> ResolveResult:
    """Final decision with delivery dedup and semantic dedup (spec 5a-5e)."""

    # spec 5b: skip
    if judge.decision == "skip" or not judge.message:
        return ResolveResult(decision="skip")

    # spec 5c: delivery dedup by cited items (禁用用于测试)
    delivery_key = _build_delivery_key(judge.cited_item_ids)
    # if delivery_key and state_store.was_delivered(delivery_key, _DELIVERY_WINDOW):
    #     logger.info("delivery dedup hit: key=%s", delivery_key[:16])
    #     return ResolveResult(decision="skip", delivery_key=delivery_key)

    # spec 5d: semantic dedup simplified (禁用用于测试)
    # content_hash = _content_hash(judge.message)
    # if state_store.was_delivered(content_hash, _DELIVERY_WINDOW * 2):
    #     logger.info("semantic dedup hit: hash=%s", content_hash[:16])
    #     return ResolveResult(decision="skip", delivery_key=delivery_key)

    # spec 5e: send
    effects = _build_side_effects(judge.cited_item_ids, delivery_key, state_store, mcp_pool, sources)
    return ResolveResult(
        decision="send",
        message=judge.message,
        cited_item_ids=judge.cited_item_ids,
        delivery_key=delivery_key,
        side_effects=effects,
    )


def _build_delivery_key(cited: list[str]) -> str:
    if not cited:
        return ""
    raw = ",".join(sorted(cited))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def _build_side_effects(
    cited: list[str],
    delivery_key: str,
    store: ProactiveStateStore,
    mcp_pool=None,
    sources: list = None,
) -> list:
    """Create side effect callbacks: mark_delivery, ack sources (spec 7a, 7d, 7b-7c)."""
    effects = []

    def mark_delivery():
        store.mark_sent(delivery_key)
        store.mark_sent(_content_hash(""))
        logger.info("delivery marked: key=%s", delivery_key[:16])

    effects.append(mark_delivery)

    # spec 7b-7c: ACK 被引用的条目（参考 akashic-agent）
    if cited and mcp_pool and sources:
        async def ack_cited_items():
            for source in sources:
                if not source.spec.ack_tool:
                    continue
                try:
                    await mcp_pool.call(
                        source.spec.server,
                        source.spec.ack_tool,
                        {"event_ids": cited}
                    )
                    logger.info("ack sent to source %s for %d items", source.spec.id, len(cited))
                except Exception as e:
                    logger.warning("ack failed for source %s: %s", source.spec.id, e)

        effects.append(ack_cited_items)

    return effects
