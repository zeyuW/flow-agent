"""主动消息的会话持久化和出站投递。"""

import asyncio
import logging

from flow_agent.proactive.models import DeliverResult, ResolveResult

logger = logging.getLogger(__name__)


async def deliver_message(
    resolve: ResolveResult,
    *,
    chat_id: str = "",
    session_manager=None,
    outbound_port=None,
    channel: str = "cli",
) -> DeliverResult:
    """先完成会话和出站投递，成功后再提交副作用。"""

    if resolve.decision != "send" or not resolve.message:
        return DeliverResult(
            sent=False,
            message="no message to send",
            chat_id=chat_id,
        )

    if session_manager is not None:
        try:
            session = session_manager.get_or_create(chat_id)
            await session_manager.append_messages(
                session,
                [
                    {
                        "role": "assistant",
                        "content": resolve.message,
                        "proactive": True,
                        "evidence": resolve.cited_item_ids,
                    }
                ],
            )
        except Exception:
            logger.exception("主动消息会话持久化失败")

    if outbound_port is not None:
        try:
            from flow_agent.messaging.message_bus import OutboundDispatch

            metadata = {
                "proactive": True,
                "cited": resolve.cited_item_ids,
            }
            if channel == "telegram" and chat_id:
                metadata["telegram_chat_id"] = chat_id
            outbound_port.send(
                OutboundDispatch(
                    channel=channel,
                    session_id=chat_id,
                    text=resolve.message,
                    metadata=metadata,
                )
            )
        except Exception:
            logger.exception("主动消息出站投递失败")
            return DeliverResult(
                sent=False,
                message=resolve.message,
                chat_id=chat_id,
                error="dispatch failed",
            )

    for effect in resolve.side_effects:
        try:
            effect_result = effect()
            if asyncio.iscoroutine(effect_result):
                await effect_result
        except Exception:
            logger.exception("主动消息投递后副作用失败")

    return DeliverResult(
        sent=True,
        message=resolve.message,
        chat_id=chat_id,
    )
