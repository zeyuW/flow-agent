"""MessagePushTool：Agent 主动向任意已注册通道推送消息的统一工具 (spec 4a-4d)。"""

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)

_MESSAGE_PUSH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "message_push",
        "description": "向指定通道的用户发送消息。支持文本、文件和图片。",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "目标通道名 (cli/qq/http 等)"},
                "chat_id": {"type": "string", "description": "目标会话 ID"},
                "text": {"type": "string", "description": "消息文本"},
                "file_path": {"type": "string", "description": "可选：要发送的文件路径"},
                "image_path": {"type": "string", "description": "可选：要发送的图片路径"},
            },
            "required": ["channel", "chat_id", "text"],
        },
    },
}


class MessagePushTool:
    """统一主动推送工具：注册通道发送能力，由 Agent 通过工具调用触发 (spec 4a-4b)。"""

    def __init__(self) -> None:
        # {channel_name: {"send": fn, "send_file": fn, "send_image": fn}}
        self._senders: dict[str, dict[str, Callable]] = {}

    def schema(self) -> dict:
        """返回工具 schema 用于 Agent 注册。"""
        return _MESSAGE_PUSH_SCHEMA

    def register_channel(
        self,
        name: str,
        *,
        send: Callable | None = None,
        send_file: Callable | None = None,
        send_image: Callable | None = None,
    ) -> None:
        """注册通道的发送能力 (spec 4a)。

        Args:
            name: 通道名
            send: 发送文本消息的函数
            send_file: 发送文件的函数
            send_image: 发送图片的函数
        """
        self._senders[name] = {}
        if send:
            self._senders[name]["send"] = send
        if send_file:
            self._senders[name]["send_file"] = send_file
        if send_image:
            self._senders[name]["send_image"] = send_image
        logger.info("message_push: registered channel %s (send=%s file=%s image=%s)",
                     name, send is not None, send_file is not None, send_image is not None)

    def execute(self, arguments: dict) -> str:
        """执行消息推送 (spec 4b)。

        根据 channel 参数查找对应的 sender 并调用。
        返回执行结果字符串。
        """
        channel = arguments.get("channel", "")
        chat_id = arguments.get("chat_id", "")
        text = arguments.get("text", "")
        file_path = arguments.get("file_path", "")
        image_path = arguments.get("image_path", "")

        senders = self._senders.get(channel)
        if not senders:
            return f"通道 '{channel}' 未注册或未启动"

        results = []

        # 发送文本
        if text:
            send_fn = senders.get("send")
            if send_fn:
                try:
                    send_fn(chat_id=chat_id, text=text)
                    results.append(f"文本已发送到 {channel}/{chat_id}")
                except Exception as e:
                    results.append(f"文本发送失败: {e}")
            else:
                results.append(f"通道 {channel} 不支持文本发送")

        # 发送文件
        if file_path:
            send_file_fn = senders.get("send_file")
            if send_file_fn:
                try:
                    send_file_fn(chat_id=chat_id, path=file_path)
                    results.append(f"文件已发送到 {channel}/{chat_id}")
                except Exception as e:
                    results.append(f"文件发送失败: {e}")
            else:
                results.append(f"通道 {channel} 不支持文件发送")

        # 发送图片
        if image_path:
            send_image_fn = senders.get("send_image")
            if send_image_fn:
                try:
                    send_image_fn(chat_id=chat_id, path=image_path)
                    results.append(f"图片已发送到 {channel}/{chat_id}")
                except Exception as e:
                    results.append(f"图片发送失败: {e}")
            else:
                results.append(f"通道 {channel} 不支持图片发送")

        return "\n".join(results) if results else "无内容发送"
