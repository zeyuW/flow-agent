"""历史重建：把内部消息转换为 OpenAI 兼容格式（规范 3）。

包含游标窗口、边界对齐、媒体重建、工具链展开、主动消息格式化和结果截断。
"""

import base64
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flow_agent.session.session_models import Session

logger = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 10000


def get_history(
    session: Session,
    max_messages: int = 500,
    *,
    start_index: int | None = None,
) -> list[dict[str, Any]]:
    """Rebuild session history into OpenAI-format messages (spec 3a).

    Supports two modes:
    - start_index: start from cursor position (for normal conversation)
    - max_messages: take the last N messages (for full history)

    Args:
        session: Session object with messages list.
        max_messages: Maximum messages to include.
        start_index: Start from this index (typically last_consolidated).

    Returns:
        List of OpenAI-format message dicts.
    """
    if not session.messages:
        return []

    msgs = session.messages
    total = len(msgs)

    if start_index is not None:
        start = max(0, min(start_index, total))
    else:
        start = max(0, total - max_messages)

    if start >= total:
        return []

    # 从窗口起点向前对齐到最近的用户消息或主动助手消息。
    if start > 0:
        original_start = start
        while (
            start > 0
            and msgs[start].get("role") != "user"
            and not (
                msgs[start].get("role") == "assistant"
                and msgs[start].get("proactive")
            )
        ):
            start -= 1
        if start > 0 and original_start != start:
            logger.debug("history boundary aligned from %d to %d", original_start, start)

    window = msgs[start:]
    if max_messages > 0 and len(window) > max_messages:
        window = window[-max_messages:]

    out: list[dict[str, Any]] = []
    for m in window:
        role = m.get("role", "")
        content = m.get("content", "")

        # spec 3e: Proactive messages
        if m.get("proactive") and role == "assistant":
            out.extend(_build_proactive_history_messages(str(content), m))
            continue

        # spec 3c: User content with media
        if role == "user":
            media = m.get("media", [])
            if media:
                user_content = _rebuild_user_content(str(content), media)
            else:
                user_content = str(content)
            out.append({"role": "user", "content": user_content})
            continue

        # spec 3d: Tool chain expansion
        tool_chain = m.get("tool_chain", [])
        if tool_chain and isinstance(tool_chain, list) and len(tool_chain) > 0:
            _expand_tool_chain(out, m, tool_chain)
            continue

        # Regular assistant or system message
        out.append({"role": role, "content": str(content)})

    return out


# ── Tool chain expansion (spec 3d) ──

def _expand_tool_chain(out: list, m: dict, tool_chain: list) -> None:
    """Expand a message with tool_chain into assistant(tool_calls) + tool messages."""
    for group in tool_chain:
        if not isinstance(group, dict):
            continue
        calls = group.get("calls") or []
        text = group.get("text", "")

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": text or None,
        }

        if calls:
            tool_calls_list = []
            for call in calls:
                func_name = call.get("name", "")
                func_args = call.get("arguments", "{}")
                if isinstance(func_args, dict):
                    import json
                    func_args = json.dumps(func_args, ensure_ascii=False)

                tool_calls_list.append({
                    "id": call.get("id", f"call_{len(tool_calls_list)}"),
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": func_args,
                    },
                })
            assistant_msg["tool_calls"] = tool_calls_list

        out.append(assistant_msg)

        # Add tool result messages
        for call in calls:
            result = call.get("result", "")
            if isinstance(result, dict):
                import json
                result = json.dumps(result, ensure_ascii=False)
            result_str = str(result)
            # spec 3f: Truncate long results
            result_str = _truncate_tool_result(result_str)
            out.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": result_str,
            })


# ── Tool result truncation (spec 3f) ──

def _truncate_tool_result(text: str) -> str:
    """Truncate tool result at TOOL_RESULT_MAX_CHARS, keeping head and tail."""
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    lines = text.splitlines()
    line_count = len(lines)
    head = text[:TOOL_RESULT_MAX_CHARS // 2]
    tail = text[-(TOOL_RESULT_MAX_CHARS // 4):]
    return f"Total output lines: {line_count}\n\n{head}\n\n... (truncated) ...\n\n{tail}"


# ── User content rebuild (spec 3c) ──

def _rebuild_user_content(text: str, media: list[dict]) -> list[dict[str, Any]]:
    """Build OpenAI vision-format content array with inline base64 images."""
    blocks: list[dict[str, Any]] = []

    if text:
        blocks.append({"type": "text", "text": text})

    for item in media:
        mtype = item.get("type", "")
        if mtype == "image" or (mtype == "file" and _is_image_path(item.get("path", ""))):
            path = item.get("path", "")
            if path:
                data_url = _file_to_data_url(path)
                if data_url:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "auto"},
                    })
                else:
                    blocks.append({"type": "text", "text": f"[image: {path}]"})
        elif mtype == "file":
            path = item.get("path", "")
            blocks.append({"type": "text", "text": f"[file: {path}]"})

    return blocks


def _build_proactive_history_messages(text: str, msg: dict) -> list[dict[str, Any]]:
    """Build proactive push message with context frame (spec 3e)."""
    source = msg.get("source", "unknown")
    output = [
        {
            "role": "assistant",
            "content": f"[active push] {text}",
            "proactive": True,
        },
    ]
    if source:
        output.append({
            "role": "system",
            "content": f"[active source: {source}]",
            "context_frame": True,
        })
    return output


def _is_image_path(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _file_to_data_url(path_str: str) -> str | None:
    try:
        p = Path(path_str)
        if not p.exists():
            return None
        data = p.read_bytes()
        ext = p.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(ext, "application/octet-stream")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None
