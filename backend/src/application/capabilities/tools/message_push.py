"""MessagePushTool：Agent 主动向任意已注册通道推送消息的统一工具 (spec 4a-4d)。

遵循 Tool 协议：提供 name / description / input_schema / run。
"""

import json
import logging
from typing import Any, Callable

from application.capabilities.tools.base import ToolResult

logger = logging.getLogger(__name__)

_MESSAGE_PUSH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "message_push",
        "description": "向指定通道的用户发送消息。支持文本、文件和图片。",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "目标通道名；被动回复时由运行时绑定当前通道",
                },
                "chat_id": {
                    "type": "string",
                    "description": "目标会话 ID；被动回复时由运行时绑定当前会话",
                },
                "text": {"type": "string", "description": "消息文本"},
                "file_path": {
                    "type": "string",
                    "description": "可选：要发送的文件路径",
                },
                "image_path": {
                    "type": "string",
                    "description": "可选：要发送的本地图片路径或 HTTP(S) URL",
                },
            },
            "anyOf": [
                {"required": ["text"]},
                {"required": ["file_path"]},
                {"required": ["image_path"]},
            ],
        },
    },
}


class MessagePushTool:
    """统一主动推送工具：注册通道发送能力，由 Agent 通过工具调用触发 (spec 4a-4b)。

    符合 Tool 协议，可直接注册到 ToolRegistry。
    """

    def __init__(self) -> None:
        # {channel_name: {"send": fn, "send_file": fn, "send_image": fn}}
        self._senders: dict[str, dict[str, Callable]] = {}

    # ── Tool 协议 ──

    @property
    def name(self) -> str:
        return "message_push"

    @property
    def description(self) -> str:
        return _MESSAGE_PUSH_SCHEMA["function"]["description"]

    @property
    def input_schema(self) -> dict[str, Any]:
        return _MESSAGE_PUSH_SCHEMA["function"]["parameters"]

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        """执行消息推送 (spec 4b)。"""
        result = self.execute(tool_input)
        return ToolResult(ok=True, content=result)

    # ── 兼容接口 ──

    def schema(self) -> dict:
        """返回完整 OpenAI function schema。"""
        return _MESSAGE_PUSH_SCHEMA

    def execute(self, arguments: dict) -> str:
        """执行消息推送并返回文本结果。

        Args:
            arguments: {"channel": "...", "chat_id": "...", "text": "...",
                         "file_path": "...", "image_path": "..."}
        Returns:
            执行结果字符串。
        """
        channel = arguments.get("channel", "")
        chat_id = arguments.get("chat_id", "")
        text = arguments.get("text", "")
        file_path = arguments.get("file_path", "")
        image_path = arguments.get("image_path", "")

        if not channel or not chat_id:
            return "错误：channel 和 chat_id 不能为空"
        if not text and not file_path and not image_path:
            return "错误：text、file_path、image_path 至少提供一个"

        senders = self._senders.get(channel)
        if not senders:
            return f"通道 '{channel}' 未注册或未启动"

        results = []

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

    # ── 通道注册 ──

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
            send: 发送文本消息的函数 (chat_id=, text=)
            send_file: 发送文件的函数 (chat_id=, path=)
            send_image: 发送图片的函数 (chat_id=, path=)
        """
        self._senders[name] = {}
        if send:
            self._senders[name]["send"] = send
        if send_file:
            self._senders[name]["send_file"] = send_file
        if send_image:
            self._senders[name]["send_image"] = send_image
        logger.info(
            "message_push: registered channel %s (send=%s file=%s image=%s)",
            name,
            send is not None,
            send_file is not None,
            send_image is not None,
        )

    def register_adapter(self, adapter: object) -> None:
        """注册统一渠道适配器，不暴露具体 IM 的发送函数。"""

        name = str(getattr(adapter, "name"))

        def invoke(method_name: str, *, chat_id: str, **kwargs: str) -> None:
            method = getattr(adapter, method_name)
            result = method(recipient_id=chat_id, **kwargs)
            if not getattr(result, "delivered", False):
                raise RuntimeError(getattr(result, "error", "渠道投递失败"))

        self.register_channel(
            name,
            send=lambda *, chat_id, text: invoke(
                "send_text", chat_id=chat_id, text=text
            ),
            send_file=lambda *, chat_id, path: invoke(
                "send_file", chat_id=chat_id, path=path
            ),
            send_image=lambda *, chat_id, path: invoke(
                "send_image", chat_id=chat_id, path=path
            ),
        )
