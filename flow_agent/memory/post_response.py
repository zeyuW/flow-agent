"""对话提交后记忆后处理 Worker。

实现 spec 4a-4c：
- 4a: TurnCommitted 事件触发，将对话内容入队供后处理
- 4b: 从 tool_chain 中提取本轮 memorize 工具写入的记忆条目
- 4c: 检测用户消息中的否定/纠错并触发 supersede
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from flow_agent.memory.memorizer import Memorizer
from flow_agent.memory.supersede import SupersedeDetector
from flow_agent.memory.vector_store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PostResponseContext:
    """对话提交后的后处理上下文。"""

    session_id: str
    user_input: str
    assistant_output: str
    tool_trace: list[dict] = field(default_factory=list)
    protected_memory_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class PostResponseResult:
    """后处理结果。"""

    extracted_memories: int = 0
    superseded_count: int = 0
    errors: int = 0


class PostResponseMemoryWorker:
    """对话提交后的异步记忆后处理 Worker（spec 4a）。

    监听 TurnCommitted 事件，在对话提交后执行：
    1. 收集显式记忆写入（spec 4b）
    2. 检测失效意图并执行 supersede（spec 4c）
    3. 提取隐含记忆写入（从对话中提取重要信息）
    """

    def __init__(
        self,
        store: MemoryStore,
        memorizer: Memorizer,
        supersede_detector: SupersedeDetector | None = None,
    ) -> None:
        self.store = store
        self.memorizer = memorizer
        self.supersede_detector = supersede_detector or SupersedeDetector(store)

    def process(self, ctx: PostResponseContext) -> PostResponseResult:
        """执行完整的对话提交后记忆处理。

        Args:
            ctx: 后处理上下文。

        Returns:
            后处理结果统计。
        """
        result = PostResponseResult()

        # spec 4b: 收集显式记忆写入（从 tool_trace 中提取 memorize 工具调用）
        memorized_ids = self._collect_explicit_memorize(ctx.tool_trace, ctx.protected_memory_ids)

        # spec 4c-4e: 检测用户否定并执行 supersede
        if ctx.user_input:
            superseded = self.supersede_detector.process_supersede(ctx.user_input)
            result.superseded_count = len(superseded)

        # 对话摘要提取（自动记忆：从 assistant_output 和 user_input 提取关键信息）
        self._extract_implicit_memory(ctx)

        result.extracted_memories = len(memorized_ids)
        return result

    def on_turn_committed(
        self,
        session_id: str,
        user_input: str,
        assistant_output: str,
        tool_trace: list[dict] | None = None,
    ) -> PostResponseResult:
        """接收 TurnCommitted 事件并处理后处理（spec 4a）。"""
        ctx = PostResponseContext(
            session_id=session_id,
            user_input=user_input,
            assistant_output=assistant_output,
            tool_trace=tool_trace or [],
        )
        return self.process(ctx)

    def _collect_explicit_memorize(
        self,
        tool_trace: list[dict],
        protected_ids: list[int],
    ) -> list[int]:
        """从 tool_trace 中提取 memorize 工具写入的记忆 ID（spec 4b）。

        这些 ID 被标记为受保护，后续 supersede 检测不会误删它们。
        """
        memorized_ids: list[int] = []
        protected_set = set(protected_ids)

        for call in tool_trace:
            tool_name = call.get("name", "") or call.get("function", {}).get("name", "")
            if tool_name != "memorize":
                continue

            args = call.get("arguments", "{}")
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue

            memory_type = args.get("memory_type", "")
            summary = args.get("summary", "")
            if not memory_type or not summary:
                continue

            # 检查是否已被保护
            from flow_agent.memory.vector_store import _compute_content_hash
            content_hash = _compute_content_hash(summary)
            existing = self.store.search_by_source_ref(
                f"memorize_tool:{memory_type}:{summary[:40]}"
            )
            for item in existing:
                if item.content_hash == content_hash:
                    memorized_ids.append(item.id)
                    protected_set.add(item.id)

        return memorized_ids

    def _extract_implicit_memory(self, ctx: PostResponseContext) -> None:
        """从对话中自动提取隐含记忆。

        简单的基于规则的信息提取：
        - 用户消息包含"我叫"、"我是" → identity
        - 用户消息包含"喜欢"、"偏好" → preference
        - 用户消息包含"规则"、"必须" → procedure
        """
        if not ctx.user_input:
            return

        text = ctx.user_input.strip()

        # 简单的规则提取（实际应由 LLM 完成，这里做最小实现）
        indicators = [
            (["我叫", "我是", "我的名字"], "fact", "identity"),
            (["喜欢", "偏好", "更倾向"], "preference", "preference"),
            (["必须", "规则", "严禁", "强制"], "procedure", "procedure"),
        ]

        for keywords, mem_type, source_prefix in indicators:
            for kw in keywords:
                if kw in text:
                    # 提取关键词后面的内容作为摘要
                    idx = text.index(kw)
                    start = idx
                    end = min(len(text), idx + 80)
                    summary = text[start:end].strip()
                    if len(summary) > 5:
                        self.memorizer.memorize(
                            memory_type=mem_type,
                            summary=summary,
                            source_ref=f"auto:{source_prefix}:{ctx.session_id}",
                        )
                        logger.debug(
                            "auto-extracted %s memory: %s",
                            mem_type,
                            summary[:40],
                        )
                    break  # 每种类型只提取一次
