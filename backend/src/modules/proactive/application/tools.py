"""供被动对话配置和查询主动推送策略的工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from modules.proactive.infra.gate import ProactiveStateStore
from modules.capabilities.tools.base import ToolResult


@dataclass(slots=True)
class ConfigureProactivePolicyTool:
    """把自然语言主动推送需求写入持久化策略。"""

    store: ProactiveStateStore

    @property
    def name(self) -> str:
        return "configure_proactive_policy"

    @property
    def description(self) -> str:
        return (
            "配置长时间未互动后的主动推送策略，包括静默时长和兴趣主题。"
            "用户要求不说话一段时间后主动找他、推送感兴趣内容时必须调用。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "是否启用静默主动推送",
                    "default": True,
                },
                "idle_minutes": {
                    "type": "number",
                    "minimum": 1,
                    "description": "连续多少分钟没有用户互动后允许主动推送",
                    "default": 120,
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "用户感兴趣的主题，例如 AI、编程、科技新闻",
                },
            },
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            chat_id = str(tool_input.get("__chat_id", "")).strip()
            topics_raw = tool_input.get("topics", [])
            topics = topics_raw if isinstance(topics_raw, list) else []
            policy = self.store.set_policy(
                chat_id,
                enabled=bool(tool_input.get("enabled", True)),
                idle_threshold_seconds=float(tool_input.get("idle_minutes", 120)) * 60,
                topics=[str(item) for item in topics],
            )
            return ToolResult(
                ok=True,
                content=json.dumps(
                    {
                        "enabled": policy.enabled,
                        "idle_minutes": policy.idle_threshold_seconds / 60,
                        "topics": list(policy.topics),
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            return ToolResult(ok=False, content=f"配置主动推送失败: {exc}")


@dataclass(slots=True)
class GetProactiveStatusTool:
    """查询当前聊天的主动推送策略和静默状态。"""

    store: ProactiveStateStore

    @property
    def name(self) -> str:
        return "get_proactive_status"

    @property
    def description(self) -> str:
        return "查询当前聊天的主动推送开关、静默阈值、兴趣主题和当前静默时长"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        chat_id = str(tool_input.get("__chat_id", "")).strip()
        policy = self.store.get_policy(chat_id)
        idle_seconds = self.store.get_idle_seconds(chat_id)
        return ToolResult(
            ok=True,
            content=json.dumps(
                {
                    "enabled": policy.enabled,
                    "idle_minutes": policy.idle_threshold_seconds / 60,
                    "topics": list(policy.topics),
                    "current_idle_minutes": (
                        idle_seconds / 60 if idle_seconds is not None else None
                    ),
                },
                ensure_ascii=False,
            ),
        )
