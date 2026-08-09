"""命令行渠道适配器。

CLI 也实现统一渠道协议，便于本地调试和组合根使用同一套生命周期。
"""

from __future__ import annotations

import logging

from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from interfaces.channels.base import (
    BaseChannelAdapter,
    ChannelCapabilities,
)


logger = logging.getLogger(__name__)


class CLIChannel(BaseChannelAdapter):
    """通过 stdin/stdout 接收和发送文本消息。"""

    capabilities = ChannelCapabilities(text=True)

    def __init__(self, default_session_id: str = "default") -> None:
        super().__init__()
        self.default_session_id = default_session_id
        self._last_outbound_text: str | None = None

    @property
    def name(self) -> str:
        return "cli"

    def handle_line(self, line: str, *, session_id: str | None = None) -> None:
        """把一行命令行输入发布为统一入站消息。"""

        if not self.status().running:
            self._last_error = "not_running"
            return
        text = (line or "").strip()
        if not text:
            return
        target = session_id or self.default_session_id
        try:
            self.publish_inbound(
                session_id=target,
                chat_id=target,
                sender_id="local",
                text=text,
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("CLI 入站消息发布失败")

    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult:
        del recipient_id
        self._last_outbound_text = text
        print(f"Agent: {text or ''}")
        return ChannelDeliveryResult(delivered=True)

    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        self._last_outbound_text = message.text
        logger.debug("CLI 出站消息: %s", message.text[:100])
        print(f"Agent: {message.text or ''}")
        if message.metadata.get("fallback"):
            logger.warning("CLI 收到降级消息: %s", message.text[:100])
        return ChannelDeliveryResult(delivered=True)
