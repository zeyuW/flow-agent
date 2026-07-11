"""Telegram 渠道：基于 Telegram Bot API 的消息适配器。"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from flow_agent.channels.base import MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

# Telegram Bot API 基础 URL
_TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramChannel(MessageBusChannel):
    """Telegram 渠道：支持私聊和群聊消息。"""
    
    def __init__(
        self,
        bot_token: str,
        message_bus=None,
        allowed_users: list[str] | None = None,
        allowed_groups: list[int] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.message_bus = message_bus
        self.allowed_users = set(allowed_users or [])  # 支持用户名和数字ID
        self.allowed_groups = set(allowed_groups or [])
        self._running = False
        self._offset = 0
        self._polling_task: asyncio.Task | None = None
        
    @property
    def name(self) -> str:
        return "telegram"
    
    def start(self) -> None:
        """启动 Telegram 消息轮询（同步入口，包装异步）。"""
        if self._running:
            return
        self._running = True
        
        # 订阅出站消息
        if self.message_bus:
            logger.info(f"telegram channel attempting to subscribe to channel={self.name}")
            self.message_bus.subscribe_outbound(self.name, self._on_response)
            logger.info("telegram channel subscribed to outbound messages")
        
        import threading
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._polling_loop())
        self._polling_thread = threading.Thread(target=run_async, daemon=True)
        self._polling_thread.start()
        logger.info("telegram channel started")
    
    def stop(self) -> None:
        """停止 Telegram 消息轮询。"""
        self._running = False
        logger.info("telegram channel stopped")
    
    async def _polling_loop(self) -> None:
        """轮询 Telegram Bot API 获取消息。"""
        while self._running:
            try:
                updates = self._get_updates()
                if updates:
                    for update in updates:
                        await self._handle_update(update)
                await asyncio.sleep(1.0)  # 避免过于频繁的轮询
            except Exception:
                logger.exception("telegram polling error")
                await asyncio.sleep(5.0)
    
    def _get_updates(self) -> list[dict]:
        """从 Telegram Bot API 获取更新。"""
        url = f"{_TELEGRAM_API_BASE}/bot{self.bot_token}/getUpdates"
        params = {
            "offset": self._offset + 1,
            "timeout": 10,
        }
        try:
            data = urllib.parse.urlencode(params).encode()
            req = urllib.request.Request(url, data=data, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    updates = result.get("result", [])
                    if updates:
                        self._offset = max(u.get("update_id", 0) for u in updates)
                    return updates
        except Exception:
            logger.exception("telegram get_updates failed")
        return []
    
    async def _handle_update(self, update: dict) -> None:
        """处理 Telegram 更新事件。"""
        message = update.get("message", {})
        if not message:
            return
        
        chat = message.get("chat", {})
        chat_type = chat.get("type", "")
        chat_id = chat.get("id", "")
        user = message.get("from", {})
        user_id = user.get("id", "")
        username = user.get("username", "")
        text = message.get("text", "")
        
        if chat_type == "private":
            # 私聊消息：检查用户ID或用户名
            if self.allowed_users:
                # 支持数字ID和用户名
                user_id_str = str(user_id)
                username_lower = username.lower() if username else ""
                allowed = False
                for allowed_user in self.allowed_users:
                    if allowed_user == user_id_str or (username_lower and allowed_user.lower() == username_lower):
                        allowed = True
                        break
                if not allowed:
                    return
            session_id = str(user_id)
        elif chat_type in ("group", "supergroup"):
            # 群聊消息
            if self.allowed_groups and chat_id not in self.allowed_groups:
                return
            session_id = f"telegram_group_{chat_id}"
        else:
            return
        
        if not text:
            return
        
        await self._publish_inbound(session_id, text, {
            "telegram_user_id": user_id,
            "telegram_username": username,
            "telegram_chat_id": chat_id,
            "telegram_chat_type": chat_type,
            "message_id": message.get("message_id", ""),
        })
    
    async def _publish_inbound(self, session_id: str, text: str, metadata: dict) -> None:
        """发布入站消息到 MessageBus。"""
        if not self.message_bus:
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
    
    def _on_response(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调（MessageBusChannel 接口）。"""
        if not message or not message.text:
            logger.warning("telegram outbound: empty message or text")
            return
        
        chat_id = message.metadata.get("telegram_chat_id", 0) if message.metadata else 0
        if not chat_id:
            logger.warning(f"telegram outbound: no telegram_chat_id in metadata: {message.metadata}")
            return
        
        try:
            self._send_text(chat_id=chat_id, text=message.text)
        except Exception:
            logger.exception("telegram outbound send failed")
    
    def on_outbound(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调（兼容旧接口）。"""
        self._on_response(message)
    
    def _send_text(self, chat_id: int, text: str, max_retries: int = 3) -> None:
        """发送文本消息到指定会话，带重试机制。"""
        url = f"{_TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram 消息长度限制
            "parse_mode": "HTML",
        }
        
        for attempt in range(max_retries):
            try:
                result = self._post_api(url, payload)
                if result:
                    logger.info(f"telegram send_text succeeded on attempt {attempt + 1}")
                    return
            except Exception as e:
                logger.warning(f"telegram send_text attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"telegram send_text failed after {max_retries} attempts")
    
    def _post_api(self, url: str, payload: dict) -> dict:
        """调用 Telegram Bot HTTP API。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            logger.exception("telegram POST %s failed", url)
            return {}
    
    # ── 供 MessagePushTool 使用 ──
    
    def send(self, *, chat_id: str, text: str) -> None:
        """发送文本消息到指定会话。"""
        if chat_id.startswith("telegram_group_"):
            group_id = int(chat_id.replace("telegram_group_", ""))
            self._send_text(group_id, text)
        else:
            self._send_text(int(chat_id), text)
    
    def send_file(self, *, chat_id: str, path: str) -> None:
        """发送文件到指定会话。"""
        logger.info("telegram send_file: chat=%s path=%s (API 待实现)", chat_id, path)
    
    def send_image(self, *, chat_id: str, path: str) -> None:
        """发送图片到指定会话。"""
        logger.info("telegram send_image: chat=%s path=%s (API 待实现)", chat_id, path)
