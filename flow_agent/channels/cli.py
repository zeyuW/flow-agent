import logging
from dataclasses import dataclass, field

from flow_agent.channels.base import ChannelStatus, MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.messaging.message_bus import MessageBus


logger = logging.getLogger(__name__)


@dataclass
class CLIChannel(MessageBusChannel):
    """CLI 渠道：基于 MessageBus 的 stdin/stdout 渠道。

    入站：读取用户输入 → 封装 InboundMessage → publish_inbound 到 MessageBus
    出站：通过 subscribe_outbound 订阅 → on_outbound 回调接收 → print 到 stdout
    """

    message_bus: MessageBus
    default_session_id: str = "default"
    _running: bool = False
    _last_error: str | None = None
    _last_outbound_text: str | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return "cli"

    def start(self) -> None:
        self._running = True
        self._last_error = None
        # 订阅出站消息
        self.message_bus.subscribe_outbound(self)
        logger.info("cli channel started (message bus connected)")

    def stop(self) -> None:
        self._running = False
        self.message_bus.outbound.unsubscribe(self)
        logger.info("cli channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def handle_line(self, line: str, *, session_id: str | None = None) -> str | None:
        """处理一行用户输入。

        封装为 InboundMessage 后通过 MessageBus 发布到入站队列。
        返回值为 None（回复通过 outbound 回调异步处理）。
        """
        if not self._running:
            self._last_error = "not_running"
            return None
        text = (line or "").strip()
        if not text:
            return None
        inbound = InboundMessage(
            channel=self.name,
            session_id=session_id or self.default_session_id,
            text=text,
        )
        try:
            self.message_bus.publish_inbound(inbound)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("cli channel publish failed")
            return None
        return None  # 回复通过 on_outbound 异步处理

    def on_outbound(self, message: OutboundMessage) -> None:
        """接收出站回复并输出到 stdout。

        由 MessageBus 在 dispatch_outbound 时自动调用。
        """
        self._last_outbound_text = message.text
        # 出站文本通过 print 输出，供 main.py 的 CLI 循环显示
        logger.debug("cli outbound: %s", message.text[:100])