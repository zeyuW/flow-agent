"""漂移模式内置工具：read_file, write_file, message_push, finish_drift (spec 3b, 4b, 4d)。"""

from pathlib import Path

_DRIFT_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定路径的文件内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入内容到指定路径的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "写入内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "message_push",
            "description": "向用户发送一条消息。调用后只允许 write_file 和 finish_drift 收尾",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "消息文本"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_drift",
            "description": "完成本次漂移执行，保存技能状态和运行记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "本次运行的摘要"},
                    "skill_name": {"type": "string", "description": "执行的技能名"},
                    "next_step": {"type": "string", "description": "下次漂移的建议步骤"},
                },
                "required": ["summary"],
            },
        },
    },
]

# message_push 后允许的工具
_POST_PUSH_TOOLS = {"write_file", "finish_drift"}


def get_drift_tool_schemas() -> list[dict]:
    """返回漂移模式的工具 schema 列表。"""
    return _DRIFT_TOOL_SCHEMAS


def get_post_push_tool_schemas() -> list[dict]:
    """返回 message_push 后的受限工具集 (spec 4b)。"""
    return [t for t in _DRIFT_TOOL_SCHEMAS if t["function"]["name"] in _POST_PUSH_TOOLS]


def dispatch_drift_tool(tool_name: str, arguments: dict, ctx: dict) -> str:
    """分发执行漂移内置工具 (spec 4d)。

    ctx 是一个可变字典，包含：
        - "message": str — 暂存待发送消息
        - "pushed": bool — 是否已调用过 message_push
        - "skills": list[DriftSkill]
        - "runs": list[DriftRun]
        - "workspace": str — 工作区根目录
    """
    if tool_name == "read_file":
        return _read_file(arguments.get("path", ""), ctx.get("workspace", ""))
    elif tool_name == "write_file":
        return _write_file(
            arguments.get("path", ""),
            arguments.get("content", ""),
            ctx.get("workspace", ""),
        )
    elif tool_name == "message_push":
        ctx["message"] = arguments.get("text", "")
        ctx["pushed"] = True
        return "消息已暂存"
    elif tool_name == "finish_drift":
        from flow_agent.proactive.drift_models import DriftRun
        import datetime

        skill_name = arguments.get("skill_name", "")
        summary = arguments.get("summary", "")
        next_step = arguments.get("next_step", "")

        # 更新技能状态
        for skill in ctx.get("skills", []):
            if skill.name == skill_name:
                state = skill.state
                state["run_count"] = state.get("run_count", 0) + 1
                state["last_run"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if next_step:
                    state["next"] = next_step

        ctx["runs"].append(DriftRun(
            skill_name=skill_name,
            action=summary,
            result="完成",
            status="completed",
        ))
        ctx["finished"] = True
        return f"漂移完成: {summary}"
    else:
        return f"未知工具: {tool_name}"


def _read_file(path: str, workspace: str) -> str:
    try:
        target = _resolve_workspace_path(path, workspace)
        return target.read_text(encoding="utf-8")[:4000]
    except Exception as e:
        return f"读取失败: {e}"


def _write_file(path: str, content: str, workspace: str) -> str:
    try:
        target = _resolve_workspace_path(path, workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
        return f"写入成功: {target}"
    except Exception as e:
        return f"写入失败: {e}"


def _resolve_workspace_path(path: str, workspace: str) -> Path:
    """把漂移文件操作限制在显式工作目录内。"""

    root = Path(workspace).resolve()
    if not str(path).strip():
        raise ValueError("路径不能为空")
    raw = Path(path).expanduser()
    target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not target.is_relative_to(root):
        raise ValueError("路径越出漂移工作目录")
    return target


import os
from pathlib import Path
