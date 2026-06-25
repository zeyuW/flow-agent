"""通道启动入口：统一启动所有已配置通道并注册到 MessagePushTool (spec 1a-1f)。"""

import asyncio
import logging

from flow_agent.channels.base import Channel
from flow_agent.channels.channel_manager import ChannelManager
from flow_agent.messaging.message_bus import MessageBus

logger = logging.getLogger(__name__)


async def start_channels(
    *,
    channels: list[Channel],
    message_bus: MessageBus,
    manager: ChannelManager | None = None,
) -> dict[str, Channel]:
    """启动所有通道并统一注册出站订阅 (spec 1a)。

    每个通道启动后自动调用 message_bus.subscribe_outbound() 注册出站回调。
    如果提供 manager，同时注册到 ChannelManager 供运维管理。
    返回 {channel_name: channel} 字典供后续注册 MessagePushTool。
    """
    started: dict[str, Channel] = {}

    for channel in channels:
        name = channel.name
        logger.info("starting channel: %s", name)
        try:
            # 启动通道（内部自行调用 subscribe_outbound）
            if hasattr(channel, 'start_async'):
                await channel.start_async()
            else:
                # 同步启动包装在线程中
                await asyncio.to_thread(channel.start)

            if manager:
                manager.register(channel)

            started[name] = channel
            logger.info("channel started: %s", name)
        except Exception:
            logger.exception("failed to start channel: %s", name)

    return started


async def stop_channels(channels: dict[str, Channel]) -> None:
    """停止所有已启动的通道。"""
    for name, channel in channels.items():
        logger.info("stopping channel: %s", name)
        try:
            if hasattr(channel, 'stop_async'):
                await channel.stop_async()
            else:
                await asyncio.to_thread(channel.stop)
        except Exception:
            logger.exception("failed to stop channel: %s", name)
