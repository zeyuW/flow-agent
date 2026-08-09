"""统一外部渠道适配协议和生命周期基类。

本模块是 `interfaces.channels` 的唯一协议入口。具体平台只实现自己的协议
解析和发送逻辑，消息总线、对话业务和进程生命周期由外部注入。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from infra.bus.types import InboundMessage
from infra.bus.event import EventBus
from infra.bus.message import MessageBus
from infra.bus.types import ChannelDeliveryResult, OutboundMessage


@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    """一个渠道支持的外部消息能力。"""

    text: bool = True
    file: bool = False
    image: bool = False
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class ChannelContext:
    """渠道运行时依赖，由组合根统一创建并注入。"""

    bus: MessageBus
    event_bus: EventBus
    log: logging.Logger
    attachment_dir: Path = Path(".")


@dataclass(frozen=True, slots=True)
class ChannelStatus:
    """渠道当前运行状态。"""

    running: bool
    last_error: str | None = None


class ChannelAdapter(Protocol):
    """所有外部消息渠道必须实现的统一协议。"""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ChannelCapabilities: ...

    def start(self, context: ChannelContext) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def status(self) -> ChannelStatus: ...

    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult: ...

    def send_file(self, *, recipient_id: str, path: str) -> ChannelDeliveryResult: ...

    def send_image(self, *, recipient_id: str, path: str) -> ChannelDeliveryResult: ...


class BaseChannelAdapter(ABC):
    """实现渠道公共生命周期和消息规范化的基类。"""

    capabilities = ChannelCapabilities()

    def __init__(self) -> None:
        self._context: ChannelContext | None = None
        self._running = False
        self._last_error: str | None = None
        self._subscribed = False

    @property
    @abstractmethod
    def name(self) -> str:
        """返回注册表中的唯一渠道名。"""

    def start(self, context: ChannelContext) -> None:
        """注入运行时依赖并启动平台入口。"""

        if self._running:
            return
        self._context = context
        self._last_error = None
        try:
            context.bus.subscribe_outbound(self.name, self.on_outbound)
            self._subscribed = True
            # 先标记运行中，平台 worker 启动后即可安全读取状态。
            self._running = True
            self._start_platform()
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            if self._subscribed:
                context.bus.unsubscribe_outbound(self.name, self.on_outbound)
                self._subscribed = False
            self._context = None
            raise

    def stop(self) -> None:
        """停止平台入口并取消出站订阅。"""

        if not self._running and not self._subscribed:
            return
        self._running = False
        context = self._context
        try:
            self._stop_platform()
        except (Exception, KeyboardInterrupt) as exc:
            self._last_error = str(exc)
            raise
        finally:
            if context is not None and self._subscribed:
                context.bus.unsubscribe_outbound(self.name, self.on_outbound)
            self._subscribed = False
            self._context = None

    def join(self, timeout: float | None = None) -> None:
        """等待平台内部 worker；无 worker 的渠道无需额外处理。"""

        del timeout

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def on_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        """将总线出站消息交给平台适配器。"""

        try:
            return self._deliver_outbound(message)
        except Exception as exc:
            self._last_error = str(exc)
            self._context_log_exception("渠道出站投递失败", exc)
            return ChannelDeliveryResult(
                delivered=False,
                retryable=True,
                error=str(exc) or "channel delivery failed",
            )

    def publish_inbound(
        self,
        *,
        session_id: str,
        chat_id: str,
        sender_id: str,
        text: str,
        media: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """把平台消息规范化后发布到总线。"""

        if self._context is None:
            raise RuntimeError(f"渠道 {self.name} 尚未启动")
        self._context.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                session_id=session_id,
                text=text,
                sender=sender_id,
                media=list(media),
                metadata=dict(metadata or {}),
                chat_id=chat_id,
            )
        )

    def send_file(self, *, recipient_id: str, path: str) -> ChannelDeliveryResult:
        """默认文件能力：明确返回不支持，而不是抛出平台异常。"""

        del recipient_id, path
        return ChannelDeliveryResult(
            delivered=False,
            retryable=False,
            error=f"channel {self.name} does not support file delivery",
        )

    def send_image(self, *, recipient_id: str, path: str) -> ChannelDeliveryResult:
        """默认图片能力：明确返回不支持，而不是抛出平台异常。"""

        del recipient_id, path
        return ChannelDeliveryResult(
            delivered=False,
            retryable=False,
            error=f"channel {self.name} does not support image delivery",
        )

    @abstractmethod
    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult:
        """发送主动文本消息。"""

    def _start_platform(self) -> None:
        """启动平台入口；纯同步渠道可以使用默认实现。"""

    def _stop_platform(self) -> None:
        """停止平台入口；纯同步渠道可以使用默认实现。"""

    @abstractmethod
    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        """发送消息总线分发的出站消息。"""

    def _context_log_exception(self, message: str, exc: Exception) -> None:
        if self._context is not None:
            self._context.log.exception(message, exc_info=exc)
