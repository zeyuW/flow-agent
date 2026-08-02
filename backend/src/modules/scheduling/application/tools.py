"""供 Agent 创建、查询和取消定时任务的内置工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.scheduling.application.runtime import DEFAULT_TIMEZONE, SchedulerService
from modules.capabilities.tools.base import ToolResult


@dataclass(slots=True)
class ScheduleTaskTool:
    service: SchedulerService

    @property
    def name(self) -> str:
        return "schedule_task"

    @property
    def description(self) -> str:
        return (
            "创建提醒或定时执行任务。支持几分钟后、指定日期时间、每天固定时间、"
            "每隔一段时间；需要查询新闻、天气或调用工具时使用 agent 类型。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "trigger": {
                    "type": "string",
                    "enum": ["after", "at", "daily", "every"],
                    "description": "after=延时一次，at=指定时间一次，daily=每天，every=固定间隔",
                },
                "when": {
                    "type": "string",
                    "description": "after/every 使用 10m、2h；daily 使用 08:30；at 使用 HH:MM 或 ISO 时间",
                },
                "task_type": {
                    "type": "string",
                    "enum": ["reminder", "agent"],
                    "description": "reminder 直接推送原文；agent 到期后调用 Agent 和工具执行任务",
                },
                "message": {"type": "string", "description": "提醒内容或到期后要执行的任务"},
                "name": {"type": "string", "description": "可选任务名称"},
                "timezone": {
                    "type": "string",
                    "description": "IANA 时区，默认 Asia/Shanghai",
                    "default": DEFAULT_TIMEZONE,
                },
            },
            "required": ["trigger", "when", "task_type", "message"],
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            task = self.service.create_task(
                trigger=str(tool_input.get("trigger", "")),
                when=str(tool_input.get("when", "")),
                task_type=str(tool_input.get("task_type", "reminder")),
                message=str(tool_input.get("message", "")),
                name=str(tool_input.get("name", "")),
                timezone_name=str(tool_input.get("timezone") or DEFAULT_TIMEZONE),
                channel=str(tool_input.get("__channel", "")),
                session_id=str(tool_input.get("__session_id", "")),
                chat_id=str(tool_input.get("__chat_id", "")),
            )
            return ToolResult(
                ok=True,
                content=json.dumps(task.to_dict(), ensure_ascii=False),
            )
        except Exception as exc:
            return ToolResult(ok=False, content=f"创建定时任务失败: {exc}")


@dataclass(slots=True)
class ListScheduledTasksTool:
    service: SchedulerService

    @property
    def name(self) -> str:
        return "list_scheduled_tasks"

    @property
    def description(self) -> str:
        return "查看当前会话尚未完成或取消的提醒和定时任务"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        session_id = str(tool_input.get("__session_id", ""))
        tasks = [task.to_dict() for task in self.service.list_tasks(session_id)]
        return ToolResult(
            ok=True,
            content=json.dumps({"count": len(tasks), "tasks": tasks}, ensure_ascii=False),
        )


@dataclass(slots=True)
class CancelScheduledTaskTool:
    service: SchedulerService

    @property
    def name(self) -> str:
        return "cancel_scheduled_task"

    @property
    def description(self) -> str:
        return "根据任务 ID 取消当前会话中的提醒或周期任务"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "任务 ID"}},
            "required": ["task_id"],
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        cancelled = self.service.cancel_task(
            str(tool_input.get("task_id", "")),
            str(tool_input.get("__session_id", "")),
        )
        return ToolResult(
            ok=cancelled,
            content="定时任务已取消" if cancelled else "未找到可取消的定时任务",
        )


class CurrentTimeTool:
    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return "读取系统当前日期、时间和时区，用于回答现在几点或计算定时任务"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA 时区，默认 Asia/Shanghai",
                    "default": DEFAULT_TIMEZONE,
                }
            },
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        name = str(tool_input.get("timezone") or DEFAULT_TIMEZONE)
        try:
            current = datetime.now(ZoneInfo(name))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            return ToolResult(ok=False, content=f"读取当前时间失败: {exc}")
        return ToolResult(
            ok=True,
            content=json.dumps(
                {"timezone": name, "current_time": current.isoformat()},
                ensure_ascii=False,
            ),
        )
