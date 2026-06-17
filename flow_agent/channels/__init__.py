"""Channels: unified inbound/outbound integrations."""

from flow_agent.channels.base import MessageBusChannel
from flow_agent.channels.models import OutboundSubscriber

__all__ = ["MessageBusChannel", "OutboundSubscriber"]