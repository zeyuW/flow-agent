"""记忆提示词注入块构建器。

实现 spec 3f：将检索结果格式化为结构化的提示词注入块，
包含四个部分：强制约束、用户偏好、待跟进需求与任务、相关历史。
"""

from modules.memory.infra.retriever import RetrievalHit


def format_injection_block(
    hits: list[RetrievalHit],
    max_chars: int = 2000,
) -> str:
    """将检索结果格式化为提示词注入块（spec 3f）。

    分组策略：
    - procedure 类型 → 强制约束（最高优先级）
    - preference 类型 → 流程规范
    - need / task 类型 → 待跟进需求与任务
    - event / fact 类型 → 相关历史

    Args:
        hits: 检索命中列表（已按分数排序）。
        max_chars: 注入块的最大字符数。

    Returns:
        格式化的记忆注入块文本，可直接插入提示词。
    """
    if not hits:
        return ""

    procedures: list[str] = []
    preferences: list[str] = []
    pending_items: list[str] = []
    history_items: list[str] = []

    for hit in hits:
        item = hit.item
        if item.status != "active":
            continue
        summary = f"- {item.summary}"
        if item.memory_type == "procedure":
            procedures.append(summary)
        elif item.memory_type == "preference":
            preferences.append(summary)
        elif item.memory_type in {"need", "task"}:
            pending_items.append(summary)
        else:
            # event、fact 以及未分类的记忆放入相关历史。
            history_items.append(summary)

    sections: list[tuple[str, str, list[str]]] = [
        ("[强制约束 - 必须执行]", "procedures", procedures),
        ("[流程规范 - 用户偏好与规则]", "preferences", preferences),
        ("[待跟进 - 用户需求与任务]", "pending", pending_items),
        ("[相关历史 - 过往对话事件]", "history", history_items),
    ]

    lines: list[str] = []

    # 预算分配：约束优先，其次是偏好、待跟进事项和相关历史。
    budgets = {
        "procedures": int(max_chars * 0.35),
        "preferences": int(max_chars * 0.25),
        "pending": int(max_chars * 0.20),
        "history": int(max_chars * 0.20),
    }

    for header, key, items in sections:
        if not items:
            continue
        budget = budgets.get(key, max_chars)
        section_lines = [f"\n{header}"]
        section_chars = len(header)
        for item in items:
            item_chars = len(item) + 1
            if section_chars + item_chars > budget:
                break
            section_lines.append(item)
            section_chars += item_chars
        if len(section_lines) > 1:
            lines.extend(section_lines)

    if not lines:
        return ""

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 3] + "..."

    return result


def format_injection_block_full(hits: list[RetrievalHit]) -> str:
    """不受字符限制的完整注入块（用于调试和日志）。"""
    return format_injection_block(hits, max_chars=10000)
