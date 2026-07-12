"""Telegram 渠道：基于 Telegram Bot API 的消息适配器。"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.channels.protocol import Channel, ChannelContext, ChannelStatus
from flow_agent.messaging.event_bus import Event, EventSubscriber, StreamDeltaReady, ToolCallStarted, ToolCallCompleted

logger = logging.getLogger(__name__)

# Telegram Bot API 基础 URL
_TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramChannel(Channel, EventSubscriber):
    """Telegram 渠道：支持私聊和群聊消息。"""
    
    # 流式输出配置参数
    _STREAM_MIN_INTERVAL_S = 2.5  # 最小更新间隔（秒）
    _STREAM_MIN_CHARS = 200        # 最小字符增长数
    _STREAM_MAX_LENGTH = 3900      # 消息最大长度
    
    def __init__(
        self,
        bot_token: str,
        allowed_users: list[str] | None = None,
        allowed_groups: list[int] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.allowed_users = set(allowed_users or [])  # 支持用户名和数字ID
        self.allowed_groups = set(allowed_groups or [])
        self._running = False
        self._offset = 0
        self._context: ChannelContext | None = None
        self._last_error: str | None = None
        self._pending_messages: dict[str, int] = {}  # session_id -> message_id
        
        # 流式输出缓冲区
        self._stream_buffers: dict[str, dict[str, Any]] = {}  # session_id -> {"content": str, "last_sent": str, "last_time": float}
        self._stream_locks: dict[str, asyncio.Lock] = {}  # session_id -> asyncio.Lock
        
    @property
    def name(self) -> str:
        return "telegram"
    
    async def start(self, ctx: ChannelContext) -> None:
        """启动 Telegram 渠道"""
        if self._running:
            return
        self._running = True
        self._context = ctx
        
        # 订阅出站消息
        ctx.bus.subscribe_outbound(self.name, self._on_response)
        logger.info("telegram channel subscribed to outbound messages")
        
        # 订阅流式输出事件
        ctx.event_bus.subscribe(self)
        logger.info("telegram channel subscribed to event bus")
        
        # 启动轮询（阻塞，直到 stop 被调用）
        self._polling_task = asyncio.create_task(self._polling_loop())
        logger.info("telegram channel started")
        
        # 等待轮询任务完成（当 stop 被调用时）
        try:
            await self._polling_task
        except asyncio.CancelledError:
            logger.info("telegram polling task cancelled")
    
    async def stop(self) -> None:
        """停止 Telegram 渠道"""
        self._running = False
        logger.info("telegram channel stopped")
    
    def status(self) -> ChannelStatus:
        """获取渠道状态"""
        return ChannelStatus(running=self._running, last_error=self._last_error)
    
    def on_event(self, event: Event) -> None:
        """处理事件总线事件"""
        if isinstance(event, StreamDeltaReady):
            self._on_stream_delta(event)
        elif isinstance(event, ToolCallStarted):
            self._on_tool_call_started(event)
        elif isinstance(event, ToolCallCompleted):
            self._on_tool_call_completed(event)
    
    def _on_stream_delta(self, event: StreamDeltaReady) -> None:
        """处理流式输出增量事件"""
        if event.channel != self.name:
            return
        
        chat_id = event.chat_id
        delta = event.delta
        
        # 初始化缓冲区
        if event.session_id not in self._stream_buffers:
            self._stream_buffers[event.session_id] = {
                "content": "",
                "last_sent": "",
                "last_time": 0.0,
            }
            self._stream_locks[event.session_id] = asyncio.Lock()
        
        buffer = self._stream_buffers[event.session_id]
        buffer["content"] += delta
        
        # 检查是否满足更新条件
        import time
        now = time.time()
        content_len = len(buffer["content"])
        last_len = len(buffer["last_sent"])
        time_diff = now - buffer["last_time"]
        
        # 降低更新条件：间隔1秒或字符增长50
        force = False
        if time_diff >= 1.0 and (content_len - last_len) >= 50:
            force = True
        
        if force:
            # 获取锁
            lock = self._stream_locks[event.session_id]
            if lock.locked():
                return  # 如果正在更新，跳过
            
            # 更新消息
            try:
                # 裁剪内容避免过长
                display_content = buffer["content"][-self._STREAM_MAX_LENGTH:]
                
                if event.session_id not in self._pending_messages:
                    # 发送初始消息
                    result = self._send_text(chat_id=int(chat_id), text=display_content)
                    if result and result.get("ok"):
                        message_id = result.get("result", {}).get("message_id")
                        self._pending_messages[event.session_id] = message_id
                else:
                    # 编辑已有消息
                    message_id = self._pending_messages[event.session_id]
                    self._edit_message(chat_id=int(chat_id), message_id=message_id, text=display_content)
                
                # 更新缓冲区状态
                buffer["last_sent"] = buffer["content"]
                buffer["last_time"] = now
            except Exception as e:
                logger.exception(f"Failed to update stream message: {e}")
    
    def _on_tool_call_started(self, event: ToolCallStarted) -> None:
        """处理工具调用开始事件"""
        if event.channel != self.name:
            return
        
        chat_id = event.chat_id
        tool_name = event.tool_name
        tool_args = event.tool_args
        
        # 发送工具调用状态消息
        text = f"🔧 调用工具: {tool_name}"
        if tool_args:
            args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
            text += f"\n参数: {args_str}"
        
        self._send_text(chat_id=int(chat_id), text=text)
    
    def _on_tool_call_completed(self, event: ToolCallCompleted) -> None:
        """处理工具调用完成事件"""
        if event.channel != self.name:
            return
        
        chat_id = event.chat_id
        tool_name = event.tool_name
        result = event.result
        
        # 发送工具调用结果消息
        text = f"✅ 工具完成: {tool_name}"
        if result:
            text += f"\n结果: {result[:200]}..."  # 限制长度
        
        self._send_text(chat_id=int(chat_id), text=text)
    
    def _edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """编辑已有消息，支持HTML格式，失败时降级为纯文本"""
        url = f"{_TELEGRAM_API_BASE}/bot{self.bot_token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:4096],
            "parse_mode": "HTML",
        }
        
        try:
            self._post_api(url, payload)
        except Exception as e:
            # HTML解析失败时降级为纯文本
            logger.warning(f"HTML parse failed, falling back to plain text: {e}")
            payload["parse_mode"] = None
            self._post_api(url, payload)
    
    def _delete_message(self, chat_id: int, message_id: int) -> None:
        """删除消息"""
        url = f"{_TELEGRAM_API_BASE}/bot{self.bot_token}/deleteMessage"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        self._post_api(url, payload)
    
    async def _polling_loop(self) -> None:
        """轮询 Telegram Bot API 获取消息。"""
        while self._running:
            try:
                updates = self._get_updates()
                if updates:
                    for update in updates:
                        await self._handle_update(update)
                await asyncio.sleep(0.5)  # 减少轮询间隔，提高响应速度
            except Exception:
                logger.exception("telegram polling error")
                await asyncio.sleep(2.0)  # 减少错误重试等待时间
    
    def _get_updates(self) -> list[dict]:
        """从 Telegram Bot API 获取更新。"""
        url = f"{_TELEGRAM_API_BASE}/bot{self.bot_token}/getUpdates"
        params = {
            "offset": self._offset + 1,
            "timeout": 5,  # 减少长轮询超时时间，提高响应速度
        }
        try:
            data = urllib.parse.urlencode(params).encode()
            req = urllib.request.Request(url, data=data, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    updates = result.get("result", [])
                    if updates:
                        self._offset = max(u.get("update_id", 0) for u in updates)
                    return updates
        except urllib.error.HTTPError as e:
            # 409 Conflict 错误通常表示多个轮询实例，忽略并重试
            if e.code == 409:
                logger.warning(f"telegram get_updates conflict (409), will retry")
                return []
            else:
                logger.error(f"telegram get_updates HTTP error: {e.code}")
                raise
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
        
        sender = str(user_id) if user_id else username
        await self._publish_inbound(session_id, text, sender, {
            "telegram_user_id": user_id,
            "telegram_username": username,
            "telegram_chat_id": chat_id,
            "telegram_chat_type": chat_type,
            "message_id": message.get("message_id", ""),
        })
    
    async def _publish_inbound(self, session_id: str, text: str, sender: str, metadata: dict) -> None:
        """发布入站消息到 MessageBus。"""
        if not self._context:
            return
        inbound = InboundMessage(
            channel=self.name,
            session_id=session_id,
            text=text,
            sender=sender,
            metadata=metadata,
        )
        self._context.bus.publish_inbound(inbound)
    
    def _on_response(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调"""
        if not message or not message.text:
            logger.warning("telegram outbound: empty message or text")
            return
        
        chat_id = message.metadata.get("telegram_chat_id", 0) if message.metadata else 0
        if not chat_id:
            logger.warning(f"telegram outbound: no telegram_chat_id in metadata: {message.metadata}")
            return
        
        # 如果该会话有待编辑的消息，说明启用了思考模式
        # 删除思考消息，发送最终答案
        if message.session_id in self._pending_messages:
            message_id = self._pending_messages[message.session_id]
            self._delete_message(chat_id=int(chat_id), message_id=message_id)
            del self._pending_messages[message.session_id]
            logger.info(f"telegram outbound: deleted thinking message {message_id} for session {message.session_id}")
        
        # 清理缓冲区
        if message.session_id in self._stream_buffers:
            del self._stream_buffers[message.session_id]
        if message.session_id in self._stream_locks:
            del self._stream_locks[message.session_id]
        
        # 发送最终答案
        try:
            self._send_text(chat_id=chat_id, text=message.text)
        except Exception:
            logger.exception("telegram outbound send failed")
    
    def _send_text(self, chat_id: int, text: str, max_retries: int = 3) -> dict:
        """发送文本消息到指定会话，带重试机制，支持HTML格式。"""
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
                    logger.info(f"telegram send_text succeeded: chat_id={chat_id}, result={result}")
                    return result
            except Exception as e:
                logger.warning(f"telegram send_text attempt {attempt + 1} failed: {e}")
                # HTML解析失败时降级为纯文本
                if "parse_mode" in payload:
                    payload["parse_mode"] = None
                    continue
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)  # 指数退避
                else:
                    logger.error(f"telegram send_text failed after {max_retries} attempts")
        return {}
    
    def _post_api(self, url: str, payload: dict) -> dict:
        """调用 Telegram Bot HTTP API。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                logger.debug(f"telegram POST response: {result}")
                return result
        except Exception:
            logger.exception("telegram POST %s failed", url)
            return {}
    
    # ── 供 MessagePushTool 使用 ──
    
    def send(self, *, chat_id: str, text: str) -> None:
        """发送文本消息到指定会话"""
        if chat_id.startswith("telegram_group_"):
            group_id = int(chat_id.replace("telegram_group_", ""))
            self._send_text(group_id, text)
        else:
            self._send_text(int(chat_id), text)
    
    def send_file(self, *, chat_id: str, path: str) -> None:
        """发送文件到指定会话"""
        logger.info("telegram send_file: chat=%s path=%s (API 待实现)", chat_id, path)
    
    def send_image(self, *, chat_id: str, path: str) -> None:
        """发送图片到指定会话"""
        logger.info("telegram send_image: chat=%s path=%s (API 待实现)", chat_id, path)
