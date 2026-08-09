"""被动回合的提交、事件广播和回复投递。"""

from __future__ import annotations

import inspect
import logging

from application.agent.app.agent import Agent
from application.passive.app.phase import TurnFlow
from infra.bus.event import EventBus, Event, TurnCommitted
from infra.bus.message import MessageBus, OutboundDispatch, OutboundPort
from infra.bus.types import MessageSender, SendMessage

logger = logging.getLogger(__name__)


class PassiveTurnDelivery:
    """保证回合提交、事件广播和出站消息的正确顺序。"""

    def __init__(
        self,
        *,
        agent: Agent,
        event_bus: EventBus | None = None,
        message_bus: MessageBus | None = None,
        outbound_port: OutboundPort | None = None,
        message_sender: MessageSender | None = None,
    ) -> None:
        self.agent = agent
        self.event_bus = event_bus
        self.outbound_port = outbound_port or (
            message_bus.outbound_port if message_bus is not None else None
        )
        self.message_sender = message_sender

    def commit_and_send(self, flow: TurnFlow) -> None:
        """先提交并广播，再把回复投入出站队列。"""

        commit_turn = self.agent.commit_turn
        if "session_id" in inspect.signature(commit_turn).parameters:
            commit_turn(
                user_input=flow.user_input,
                assistant_output=flow.final_output,
                session_id=flow.session_id,
            )
        else:
            commit_turn(
                user_input=flow.user_input,
                assistant_output=flow.final_output,
            )
        self.broadcast_turn_committed(flow)
        self.send_outbound_reply(flow)

    def broadcast_turn_committed(self, flow: TurnFlow) -> None:
        if self.event_bus is None:
            return
        event = TurnCommitted(
            trace_id=flow.trace_id,
            session_id=flow.session_id,
            user_input=flow.user_input,
            assistant_output=flow.final_output,
            tool_trace=flow.tool_trace,
        )
        event.payload["channel"] = flow.channel
        event.payload["token_stats"] = {"tool_steps": len(flow.tool_trace)}
        try:
            self.event_bus.publish(event)
            logger.debug("turn_committed event broadcast: trace=%s", flow.trace_id)
        except Exception:
            logger.exception("failed to broadcast TurnCommitted event")

    def send_outbound_reply(self, flow: TurnFlow) -> None:
        if self.message_sender is None and self.outbound_port is None:
            logger.warning("no outbound_port configured, cannot send reply")
            return
        logger.info(
            "sending outbound reply: channel=%s, text=%s",
            flow.channel,
            flow.final_output[:100],
        )
        metadata = {"trace_id": flow.trace_id, "tool_trace": flow.tool_trace}
        if flow.inbound_metadata:
            metadata.update(flow.inbound_metadata)
        request = SendMessage(
            channel=flow.channel,
            conversation_id=flow.session_id,
            text=flow.final_output,
            recipient_id=getattr(flow, "chat_id", "") or flow.session_id,
            metadata=metadata,
        )
        try:
            if self.message_sender is not None:
                self.message_sender.send(request)
            else:
                assert self.outbound_port is not None
                self.outbound_port.send(
                    OutboundDispatch(
                        channel=request.channel,
                        session_id=request.conversation_id,
                        text=request.text,
                        chat_id=request.recipient_id,
                        metadata=dict(request.metadata),
                    )
                )
            logger.debug(
                "outbound reply dispatched: channel=%s session=%s metadata=%s",
                flow.channel,
                flow.session_id,
                list(metadata.keys()),
            )
        except Exception:
            logger.exception("failed to dispatch outbound reply")

    def send_error_reply(self, flow: TurnFlow, exc: Exception) -> None:
        if self.message_sender is None and self.outbound_port is None:
            return
        metadata: dict[str, object] = {"trace_id": flow.trace_id, "error": True}
        if flow.inbound_metadata:
            metadata.update(flow.inbound_metadata)
        request = SendMessage(
            channel=flow.channel,
            conversation_id=flow.session_id,
            text=f"处理消息时出错: {exc}",
            recipient_id=getattr(flow, "chat_id", "") or flow.session_id,
            metadata=metadata,
        )
        try:
            if self.message_sender is not None:
                self.message_sender.send(request)
            else:
                assert self.outbound_port is not None
                self.outbound_port.send(
                    OutboundDispatch(
                        channel=request.channel,
                        session_id=request.conversation_id,
                        text=request.text,
                        chat_id=request.recipient_id,
                        metadata=dict(request.metadata),
                    )
                )
        except Exception:
            logger.exception("failed to send error reply")
