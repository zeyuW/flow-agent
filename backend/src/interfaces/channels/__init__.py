"""统一外部消息渠道适配层。"""

from interfaces.channels.base import (
    BaseChannelAdapter,
    ChannelAdapter,
    ChannelCapabilities,
    ChannelContext,
    ChannelStatus,
)
from interfaces.channels.service import ChannelService, register_builtin_channels

__all__ = [
    "ChannelAdapter",
    "BaseChannelAdapter",
    "ChannelCapabilities",
    "ChannelContext",
    "ChannelStatus",
    "ChannelService",
    "register_builtin_channels",
]
