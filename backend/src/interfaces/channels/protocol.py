"""渠道协议：统一接口定义。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChannelStatus:
    """渠道状态"""
    running: bool
    last_error: str | None = None


@dataclass
class ChannelContext:
    """渠道运行时上下文"""
    bus: object  # MessageBus
    event_bus: object  # EventBus
    log: object  # Logger


class Channel(Protocol):
    """渠道协议：所有渠道必须实现此接口"""

    @property
    def name(self) -> str:
        """渠道名称"""
        ...

    async def start(self, ctx: ChannelContext) -> None:
        """启动渠道"""
        ...

    async def stop(self) -> None:
        """停止渠道"""
        ...

    def status(self) -> ChannelStatus:
        """获取渠道状态"""
        ...
