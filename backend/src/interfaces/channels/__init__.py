"""Channels: unified inbound/outbound integrations.

渠道通过 subscribe_outbound 注册 on_response 回调，
MessageBus 后台 dispatch_outbound 任务调用回调发送消息。
"""

from typing import TYPE_CHECKING

from interfaces.channels.base import Channel, ChannelStatus, MessageBusChannel
from interfaces.channels.models import OutboundSubscriber
from modules.conversation.domain.channel_message import InboundMessage
from modules.delivery.domain.messages import OutboundMessage

if TYPE_CHECKING:
    from interfaces.channels.cli import CLIChannel
    from interfaces.channels.http import HTTPChannel
    from interfaces.channels.qq import QQChannel
    from interfaces.channels.qqbot import QQBotChannel

__all__ = [
    "Channel",
    "ChannelStatus",
    "MessageBusChannel",
    "InboundMessage",
    "OutboundMessage",
]

if not TYPE_CHECKING:
    __all__.extend(["CLIChannel", "HTTPChannel", "QQChannel", "QQBotChannel"])
