"""QQ 官方机器人通道：基于 QQ Bot WebSocket 协议的入站/出站实现 (spec 6a-6f)。

QQ 官方 Bot API v2 使用 WebSocket 双向通信，无需轮询。
连接地址: wss://api.sgroup.qq.com/websocket
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field

from flow_agent.channels.base import ChannelStatus, MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.messaging.message_bus import MessageBus

logger = logging.getLogger(__name__)

_QQBOT_API_BASE = "https://api.sgroup.qq.com"
_QQBOT_WS_URL = "wss://api.sgroup.qq.com/websocket"


@dataclass
class QQBotChannel(MessageBusChannel):
    """QQ 官方机器人渠道 (spec 6a-6f)。

    入站：WebSocket 接收事件 → 封装 InboundMessage → publish_inbound 到 MessageBus
    出站：subscribe_outbound 注册回调 → MessageBus dispatch 调用 → HTTP POST 消息
    """

    app_id: str
    token: str
    secret: str = ""
    message_bus: MessageBus | None = None
    allowed_users: set[int] = field(default_factory=set)
    allowed_groups: set[int] = field(default_factory=set)
    _running: bool = False
    _last_error: str | None = None
    _ws: object = None  # WebSocket 连接
    _recv_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "qq"

    # ── 生命周期 ──

    def start(self) -> None:
        """同步启动入口，包装异步 start_async。"""
        if self._running:
            return
        self._last_error = None
        self._running = True

        # 注册出站订阅
        if self.message_bus:
            self.message_bus.subscribe_outbound(self.name, self._on_response)
        logger.info("qqbot channel started")

    def stop(self) -> None:
        """停止 QQ Bot 通道。"""
        if not self._running:
            return
        if self.message_bus:
            self.message_bus.unsubscribe_outbound(self.name, self._on_response)
        if self._recv_task:
            self._recv_task.cancel()
        self._running = False
        logger.info("qqbot channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    async def start_async(self) -> None:
        """异步启动：连接 WebSocket 并开始接收事件。"""
        self.start()
        try:
            ws_url = await self._get_ws_url()
            self._ws = await self._connect_ws(ws_url)
            self._recv_task = asyncio.create_task(self._recv_loop())
        except Exception as e:
            self._last_error = str(e)
            logger.exception("qqbot async start failed")

    async def stop_async(self) -> None:
        """异步停止。"""
        self.stop()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── WebSocket 连接 ──

    async def _get_ws_url(self) -> str:
        """获取 WebSocket 网关地址。"""
        import urllib.request

        req = urllib.request.Request(
            f"{_QQBOT_API_BASE}/gateway",
            headers={"Authorization": f"Bot {self.app_id}.{self.token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("url", _QQBOT_WS_URL)
        except Exception:
            logger.exception("failed to get ws url, using default")
            return _QQBOT_WS_URL

    async def _connect_ws(self, url: str):
        """建立 WebSocket 连接。"""
        # 使用标准库 asyncio 无法直接 WebSocket，此处预留接口
        # 实际使用需要 websockets 库: await websockets.connect(url)
        logger.info("qqbot would connect to: %s", url)
        return None

    # ── 事件接收循环 ──

    async def _recv_loop(self) -> None:
        """WebSocket 消息接收循环 (spec 6a)。"""
        while self._running and self._ws:
            try:
                msg = await self._ws.recv()
                await self._handle_event(json.loads(msg))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("qqbot recv error")
                await asyncio.sleep(1)

    async def _handle_event(self, event: dict) -> None:
        """处理 QQ Bot 事件 (spec 6a, 6d)。"""
        event_type = event.get("t", "")
        data = event.get("d", {})

        if event_type == "MESSAGE_CREATE":
            await self._handle_message(data)
        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            await self._handle_group_message(data)

    # ── 消息处理 ──

    async def _handle_message(self, data: dict) -> None:
        """处理私聊消息 (spec 6a, 6b)。"""
        author = data.get("author", {})
        user_id = author.get("id", "")
        content = data.get("content", "")
        user_id_int = int(user_id) if isinstance(user_id, str) and user_id.isdigit() else 0

        # 权限检查
        if self.allowed_users and user_id_int not in self.allowed_users:
            return

        # 解析消息内容
        text = self._extract_text(content)

        await self._publish_inbound(str(user_id), text, {
            "qq_user_id": user_id_int,
            "qq_openid": author.get("id", ""),
            "message_id": data.get("id", ""),
        })

    async def _handle_group_message(self, data: dict) -> None:
        """处理群聊 @ 消息 (spec 6d, 6e)。"""
        group_id = data.get("group_id", "")
        author = data.get("author", {})
        user_id = author.get("id", "")
        content = data.get("content", "")
        group_id_int = int(group_id) if isinstance(group_id, str) and group_id.isdigit() else 0

        # 群过滤：只处理配置中的群
        if self.allowed_groups and group_id_int not in self.allowed_groups:
            return

        text = self._extract_text(content)
        session_id = f"qq_group_{group_id}"

        await self._publish_inbound(session_id, text, {
            "qq_user_id": int(user_id) if isinstance(user_id, str) and user_id.isdigit() else 0,
            "qq_group_id": group_id_int,
            "message_id": data.get("id", ""),
        })

    def _extract_text(self, content: str) -> str:
        """从 QQ 消息中提取纯文本 (spec 6b)。

        QQ 消息 content 可能包含内嵌格式，需要去除 <@...>、<#...> 等标签。
        """
        if not content:
            return ""
        # 去除内嵌标签
        import re
        text = re.sub(r"<@!\d+>", "", content)  # @用户
        text = re.sub(r"<#\d+>", "", text)  # 频道引用
        return text.strip()

    async def _publish_inbound(self, session_id: str, text: str, metadata: dict) -> None:
        """发布入站消息到 MessageBus (spec 6c)。"""
        if not text or not self.message_bus:
            return
        inbound = InboundMessage(
            channel=self.name,
            session_id=session_id,
            text=text,
            metadata=metadata,
        )
        try:
            async_loop = asyncio.get_running_loop()
            async_loop.call_soon_threadsafe(self.message_bus.publish_inbound, inbound)
        except RuntimeError:
            self.message_bus.publish_inbound(inbound)

    # ── 出站回复 ──

    def _on_response(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调 (spec 3f)。

        由 MessageBus 后台 dispatch_outbound 调用。
        """
        qq_user_id = message.metadata.get("qq_user_id", 0) if message.metadata else 0
        if not qq_user_id:
            logger.warning("qq outbound: no qq_user_id")
            return
        try:
            self._send_text(chat_id=str(qq_user_id), text=message.text)
        except Exception:
            logger.exception("qq outbound send failed")

    def on_outbound(self, message: OutboundMessage) -> None:
        """兼容旧接口，转发到 _on_response。"""
        self._on_response(message)

    # ── 消息发送 (供 MessagePushTool 使用) ──

    def send(self, *, chat_id: str, text: str) -> None:
        """发送文本消息到指定会话 (spec 4d)。

        chat_id 前缀判断：
        - "qq_group_" 开头 → 群聊消息
        - 其他 → 私聊消息
        """
        if chat_id.startswith("qq_group_"):
            group_id = chat_id.replace("qq_group_", "")
            self._send_group_text(group_id, text)
        else:
            self._send_text(chat_id=chat_id, text=text)

    def send_file(self, *, chat_id: str, path: str) -> None:
        """发送文件到指定会话。"""
        logger.info("qq send_file: chat=%s path=%s (API 待实现)", chat_id, path)

    def send_image(self, *, chat_id: str, path: str) -> None:
        """发送图片到指定会话。"""
        logger.info("qq send_image: chat=%s path=%s (API 待实现)", chat_id, path)

    def _send_text(self, *, chat_id: str, text: str) -> None:
        """通过 HTTP API 发送私聊文本消息。"""
        self._post_api(f"/v2/users/{chat_id}/messages", {
            "content": text,
            "msg_type": 0,
        })

    def _send_group_text(self, group_id: str, text: str) -> None:
        """通过 HTTP API 发送群聊文本消息。"""
        self._post_api(f"/v2/groups/{group_id}/messages", {
            "content": text,
            "msg_type": 0,
        })

    def _post_api(self, path: str, payload: dict) -> dict:
        """调用 QQ Bot HTTP API。"""
        import urllib.request

        url = f"{_QQBOT_API_BASE}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bot {self.app_id}.{self.token}",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
