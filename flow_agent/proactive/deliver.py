"""Deliver: persist session and dispatch outbound message (spec 6)."""

import logging

from flow_agent.proactive.models import DeliverResult, ResolveResult

logger = logging.getLogger(__name__)


async def deliver_message(
    resolve: ResolveResult,
    *,
    chat_id: str = "",
    session_manager=None,
    outbound_port=None,
) -> DeliverResult:
    """Persist proactive session and dispatch outbound (spec 6a-6e)."""
    if resolve.decision != "send" or not resolve.message:
        return DeliverResult(sent=False, message="no message to send", chat_id=chat_id)

    # spec 6c: persist to session
    if session_manager:
        try:
            session = session_manager.get_or_create(chat_id)
            import asyncio
            await session_manager.append_messages(session, [{
                "role": "assistant",
                "content": resolve.message,
                "proactive": True,
                "evidence": resolve.cited_item_ids,
            }])
        except Exception:
            logger.exception("failed to persist proactive session")

    # spec 6d: dispatch to outbound
    if outbound_port:
        try:
            from flow_agent.messaging.message_bus import OutboundDispatch
            outbound_port.send(OutboundDispatch(
                channel="cli",
                session_id=chat_id,
                text=resolve.message,
                metadata={"proactive": True, "cited": resolve.cited_item_ids},
            ))
            logger.info("proactive message dispatched to %s", chat_id)
        except Exception:
            logger.exception("proactive dispatch failed")
            return DeliverResult(sent=False, message=resolve.message, chat_id=chat_id, error="dispatch failed")

    # spec 6e: run side effects
    for effect in resolve.side_effects:
        try:
            effect()
        except Exception:
            logger.exception("side effect failed")

    return DeliverResult(sent=True, message=resolve.message, chat_id=chat_id)
