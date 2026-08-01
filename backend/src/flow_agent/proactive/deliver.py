"""主动消息的会话持久化和出站投递。"""

import asyncio
import logging

from modules.proactive.domain.models import DeliverResult, ResolveResult

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

    if outbound_port is None:
        return DeliverResult(
            sent=False,
            message=resolve.message,
            chat_id=chat_id,
            error="outbound port unavailable",
        )

    try:
        from flow_agent.messaging.message_bus import OutboundDispatch

        metadata = {
            "proactive": True,
            "cited": resolve.cited_item_ids,
        }
        if channel == "telegram" and chat_id:
            metadata["telegram_chat_id"] = chat_id
        dispatch = OutboundDispatch(
            channel=channel,
            session_id=chat_id,
            chat_id=chat_id,
            delivery_id=resolve.delivery_key,
            text=resolve.message,
            metadata=metadata,
        )
        if hasattr(outbound_port, "send_and_wait"):
            receipt = await outbound_port.send_and_wait(dispatch, timeout=30.0)
            if not receipt.delivered:
                return DeliverResult(
                    sent=False,
                    message=resolve.message,
                    chat_id=chat_id,
                    error=receipt.error or "delivery failed",
                )
        else:
            outbound_port.send(dispatch)
    except Exception as exc:
        logger.exception("主动消息出站投递失败")
        return DeliverResult(
            sent=False,
            message=resolve.message,
            chat_id=chat_id,
            error=str(exc) or "dispatch failed",
        )

    # 主动消息只有在渠道确认送达后才进入会话历史。
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
