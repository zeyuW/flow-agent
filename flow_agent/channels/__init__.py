"""Channels: unified inbound/outbound integrations.

渠道通过 subscribe_outbound 注册 on_response 回调，
MessageBus 后台 dispatch_outbound 任务调用回调发送消息。
"""

from typing import TYPE_CHECKING

from flow_agent.channels.base import Channel, ChannelStatus, MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.channels.channel_manager import ChannelManager

if TYPE_CHECKING:
    from flow_agent.channels.cli import CLIChannel
    from flow_agent.channels.http import HTTPChannel
    from flow_agent.channels.qq import QQChannel
    from flow_agent.channels.qqbot import QQBotChannel
    from flow_agent.channels.channel_bootstrap import start_channels, stop_channels

__all__ = [
    "Channel",
    "ChannelStatus",
    "MessageBusChannel",
    "InboundMessage",
    "OutboundMessage",
    "ChannelManager",
]

if not TYPE_CHECKING:
    __all__.extend(["CLIChannel", "HTTPChannel", "QQChannel", "QQBotChannel", "start_channels", "stop_channels"])
