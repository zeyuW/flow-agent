import logging
from dataclasses import dataclass

from flow_agent.channels.base import ChannelStatus, InboundHandler
from flow_agent.channels.models import InboundMessage


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CLIChannel:
    """CLI channel: reads stdin lines and invokes inbound handler."""

    handler: InboundHandler
    default_session_id: str = "default"
    _running: bool = False
    _last_error: str | None = None

    @property
    def name(self) -> str:
        return "cli"

    def start(self) -> None:
        self._running = True
        self._last_error = None
        logger.info("cli channel started")

    def stop(self) -> None:
        self._running = False
        logger.info("cli channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def handle_line(self, line: str, *, session_id: str | None = None) -> str | None:
        """Handle one line of user input and return assistant output."""

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
            out = self.handler(inbound)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("cli channel handler failed")
            return None
        return out.text if out is not None else None

