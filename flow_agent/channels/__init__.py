"""Channels: unified inbound/outbound integrations.

渠道通过 subscribe_outbound 注册 on_response 回调，
MessageBus 后台 dispatch_outbound 任务调用回调发送消息。
"""

from flow_agent.channels.base import MessageBusChannel

__all__ = ["MessageBusChannel"]