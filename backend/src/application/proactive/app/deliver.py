"""主动消息的会话持久化和出站投递。"""

import asyncio
import logging

from application.proactive.domain.models import DeliverResult, ResolveResult
from infra.bus.types import MessageSender, SendMessage

logger = logging.getLogger(__name__)


async def deliver_message(
    resolve: ResolveResult,
    *,
    chat_id: str = "",
    session_manager=None,
    message_sender: MessageSender | None = None,
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

    if message_sender is None and outbound_port is None:
        return DeliverResult(
            sent=False,
            message=resolve.message,
            chat_id=chat_id,
            error="outbound port unavailable",
        )

    try:
        metadata = {
            "proactive": True,
            "cited": resolve.cited_item_ids,
        }
        if message_sender is not None:
            send_message = SendMessage(
                channel=channel,
                conversation_id=chat_id,
                recipient_id=chat_id,
                text=resolve.message,
                message_id=resolve.delivery_key,
                metadata=metadata,
            )
            send_and_wait = getattr(message_sender, "send_and_wait", None)
            if callable(send_and_wait):
                result = await send_and_wait(send_message, timeout=30.0)
            else:
                result = message_sender.send(send_message)
            if not result.accepted:
                return DeliverResult(
                    sent=False,
                    message=resolve.message,
                    chat_id=chat_id,
                    error=result.error or "消息未进入可靠队列",
                )
        else:
            from infra.bus.message import OutboundDispatch

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
