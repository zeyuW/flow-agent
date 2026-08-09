"""QQ 官方机器人通道：基于 QQ Bot WebSocket 协议的入站/出站实现 (spec 6a-6f)。

QQ 官方 Bot API v2 使用 WebSocket 双向通信，无需轮询。
协议流程: 获取网关地址 → WebSocket 连接 → Hello/Identify 握手 → 心跳维持 → 事件接收
"""

import asyncio
import json
import logging
import threading
from typing import Any

from interfaces.channels.base import (
    BaseChannelAdapter,
    ChannelCapabilities,
)
from infra.bus.types import ChannelDeliveryResult, OutboundMessage

try:
    import websockets
    import websockets.exceptions
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False
    websockets = None  # type: ignore

logger = logging.getLogger(__name__)

_QQBOT_API_BASE = "https://api.sgroup.qq.com"
_QQBOT_WS_URL = "wss://api.sgroup.qq.com/websocket"

# 订阅事件所需的 intents 位掩码
_INTENT_DIRECT_MESSAGE = 1 << 12      # 私聊消息
_INTENT_GROUP_C2C_EVENT = 1 << 25     # 群聊及 C2C 事件
_DEFAULT_INTENTS = _INTENT_DIRECT_MESSAGE | _INTENT_GROUP_C2C_EVENT

# WebSocket 协议 opcode
_OP_DISPATCH = 0       # 服务端推送事件
_OP_HEARTBEAT = 1      # 客户端心跳
_OP_IDENTIFY = 2       # 客户端鉴权
_OP_HELLO = 10         # 服务端握手（下发心跳间隔）
_OP_HEARTBEAT_ACK = 11 # 服务端心跳应答

# 重连参数
_RECONNECT_BASE_DELAY = 2.0   # 基础重连间隔（秒）
_RECONNECT_MAX_DELAY = 60.0   # 最大重连间隔（秒）
_RECONNECT_BACKOFF = 2.0      # 退避倍数


class QQBotChannel(BaseChannelAdapter):
    """QQ 官方机器人渠道 (spec 6a-6f)。

    入站：WebSocket 接收事件 → 封装 InboundMessage → publish_inbound 到 MessageBus
    出站：subscribe_outbound 注册回调 → MessageBus dispatch 调用 → HTTP POST 消息
    """

    capabilities = ChannelCapabilities(text=True)

    def __init__(
        self,
        app_id: str = "",
        token: str = "",
        secret: str = "",
        allowed_users: set[int] | None = None,
        allowed_groups: set[int] | None = None,
    ) -> None:
        super().__init__()
        self.app_id = app_id
        self.token = token
        self.secret = secret
        self.allowed_users = set(allowed_users or set())
        self.allowed_groups = set(allowed_groups or set())
        self._ws: object = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._main_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "qqbot"

    @property
    def enabled(self) -> bool:
        """配置有效且 websockets 库可用。"""
        return bool(self.app_id and self.token and _HAS_WEBSOCKETS)

    # ── 生命周期 ──

    def _start_platform(self) -> None:
        """在适配器自己的事件循环线程中启动 WebSocket 连接。"""

        if not self.enabled:
            raise RuntimeError("QQ 官方 Bot 缺少 app_id、token 或 websockets 依赖")
        self._thread = threading.Thread(
            target=self._run_loop,
            name="qqbot-channel",
            daemon=True,
        )
        self._thread.start()
        logger.info("QQ 官方 Bot 渠道启动")

    def _stop_platform(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(self._close_async(), loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            logger.exception("QQ 官方 Bot 停止失败")

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            self._main_task = loop.create_task(self._connection_loop())
            loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._main_task = None
            self._loop = None
            loop.close()

    async def _close_async(self) -> None:
        if self._main_task is not None and not self._main_task.done():
            self._main_task.cancel()
        await self._close_ws()

    async def _close_ws(self) -> None:
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ── 连接管理 ──

    async def _connection_loop(self) -> None:
        """WebSocket 连接与自动重连主循环。"""
        delay = _RECONNECT_BASE_DELAY
        while self._running:
            try:
                ws_url = await self._get_ws_url()
                async with websockets.connect(ws_url, ping_interval=None) as ws:
                    self._ws = ws
                    delay = _RECONNECT_BASE_DELAY
                    logger.info("qqbot connected to %s", ws_url)
                    await self._recv_loop(ws)
            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                self._last_error = str(e)
                logger.warning("qqbot disconnected: %s, will reconnect in %.1fs", e, delay)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("qqbot connection error, will reconnect")

            if not self._running:
                break
            await asyncio.sleep(delay)
            delay = min(delay * _RECONNECT_BACKOFF, _RECONNECT_MAX_DELAY)
        self._ws = None

    async def _get_ws_url(self) -> str:
        """通过 HTTP API 获取 WebSocket 网关地址。"""
        import urllib.request

        req = urllib.request.Request(
            f"{_QQBOT_API_BASE}/gateway/bot",
            headers={"Authorization": f"Bot {self.app_id}.{self.token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("url", _QQBOT_WS_URL)
        except Exception:
            logger.exception("获取网关地址失败，使用默认地址")
            return _QQBOT_WS_URL

    # ── 事件接收 ──

    async def _recv_loop(self, ws: Any) -> None:
        """WebSocket 消息接收循环。

        处理 opcode:
          - 10 (Hello): 记录心跳间隔，发送 Identify
          - 11 (Heartbeat ACK): 服务端心跳应答，忽略
          -  0 (Dispatch): 业务事件，分发到对应 handler
        """
        heartbeat_interval: float | None = None
        heartbeat_task: asyncio.Task | None = None

        try:
            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                op = msg.get("op")
                if op == _OP_HELLO:
                    heartbeat_interval = (
                        msg.get("d", {}).get("heartbeat_interval", 41250) / 1000.0
                    )
                    logger.info("qqbot hello, heartbeat_interval=%.1fs", heartbeat_interval)
                    identify_payload = json.dumps({
                        "op": _OP_IDENTIFY,
                        "d": {
                            "token": f"Bot {self.app_id}.{self.token}",
                            "intents": _DEFAULT_INTENTS,
                            "shard": [0, 1],
                            "properties": {
                                "$os": "linux",
                                "$browser": "flow-agent",
                                "$device": "flow-agent",
                            },
                        },
                    })
                    await ws.send(identify_payload)
                    if heartbeat_task is None or heartbeat_task.done():
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat_loop(ws, heartbeat_interval)
                        )
                elif op == _OP_HEARTBEAT_ACK:
                    pass
                elif op == _OP_DISPATCH:
                    await self._handle_event(msg)
                else:
                    logger.debug("qqbot unknown op=%s", op)
        finally:
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat_loop(self, ws: Any, interval: float) -> None:
        """定时发送心跳包。"""
        if interval <= 0:
            interval = 41.25
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await ws.send(json.dumps({"op": _OP_HEARTBEAT}))
            except Exception:
                logger.warning("qqbot heartbeat send failed")
                break

    # ── 事件分发 ──

    async def _handle_event(self, event: dict) -> None:
        """处理 QQ Bot 事件 (spec 6a, 6d)。"""
        event_type = str(event.get("t", ""))
        data = event.get("d", {})

        if event_type in ("READY", "RESUMED"):
            session_id = data.get("session_id", "")
            bot_id = data.get("user", {}).get("id", self.app_id)
            logger.info("qqbot ready: bot_id=%s session=%s", bot_id, session_id)
            return

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

        if self.allowed_users and user_id_int not in self.allowed_users:
            return

        text = self._extract_text(content)

        await self._publish_inbound(str(user_id), str(user_id), str(user_id), text, {
            "provider_user_id": user_id_int,
            "provider_openid": author.get("id", ""),
            "message_id": data.get("id", ""),
        })

    async def _handle_group_message(self, data: dict) -> None:
        """处理群聊 @ 消息 (spec 6d, 6e)。"""
        group_id = data.get("group_id", "")
        author = data.get("author", {})
        user_id = author.get("id", "")
        content = data.get("content", "")
        group_id_int = int(group_id) if isinstance(group_id, str) and group_id.isdigit() else 0

        if self.allowed_groups and group_id_int not in self.allowed_groups:
            return

        text = self._extract_text(content)
        session_id = f"qq_group_{group_id}"

        await self._publish_inbound(session_id, str(group_id), str(user_id), text, {
            "provider_user_id": int(user_id) if isinstance(user_id, str) and user_id.isdigit() else 0,
            "provider_group_id": group_id_int,
            "message_id": data.get("id", ""),
        })

    def _extract_text(self, content: str) -> str:
        """从 QQ 消息中提取纯文本 (spec 6b)。"""
        if not content:
            return ""
        import re
        text = re.sub(r"<@!\d+>", "", content)
        text = re.sub(r"<#\d+>", "", text)
        return text.strip()

    async def _publish_inbound(
        self,
        session_id: str,
        chat_id: str,
        sender_id: str,
        text: str,
        metadata: dict,
    ) -> None:
        """发布规范化入站消息到 MessageBus。"""
        self.publish_inbound(
            session_id=session_id,
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            metadata=metadata,
        )

    # ── 出站回复 ──

    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        """按通用 chat_id 发送出站消息。"""
        if not message or not message.text:
            return ChannelDeliveryResult(delivered=False, retryable=False, error="空出站消息")
        chat_id = message.chat_id or message.session_id
        if chat_id.startswith("qq_group_"):
            self._send_group_text(chat_id.removeprefix("qq_group_"), message.text)
        else:
            self._send_text(chat_id=chat_id, text=message.text)
        return ChannelDeliveryResult(delivered=True)

    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult:
        if recipient_id.startswith("qq_group_"):
            self._send_group_text(recipient_id.removeprefix("qq_group_"), text)
        else:
            self._send_text(chat_id=recipient_id, text=text)
        return ChannelDeliveryResult(delivered=True)

    def _send_text(self, *, chat_id: str, text: str) -> None:
        """通过 HTTP API 发送私聊文本消息。"""
        self._post_api(f"/v2/users/{chat_id}/messages", {
            "content": text[:2000],
            "msg_type": 0,
            "msg_id": "",
        })

    def _send_group_text(self, group_id: str, text: str) -> None:
        """通过 HTTP API 发送群聊文本消息。"""
        self._post_api(f"/v2/groups/{group_id}/messages", {
            "content": text[:2000],
            "msg_type": 0,
            "msg_id": "",
        })

    def _post_api(self, path: str, payload: dict) -> dict:
        """调用 QQ Bot HTTP API，返回响应 JSON。"""
        import urllib.request

        url = f"{_QQBOT_API_BASE}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bot {self.app_id}.{self.token}",
            "Content-Type": "application/json",
        }
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception:
            logger.exception("qqbot POST %s failed", path)
            return {}
