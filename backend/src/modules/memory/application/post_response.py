"""对话提交后记忆后处理 Worker。

实现 spec 4a-4c：
- 4a: TurnCommitted 事件触发，将对话内容入队供后处理
- 4b: 从工具链中提取本轮 memorize 工具写入的记忆条目
- 4c: 检测用户消息中的否定/纠错并触发 supersede
"""

import logging
from dataclasses import dataclass, field

from modules.memory.markdown_store import MarkdownStore
from modules.memory.application.memorizer import Memorizer
from modules.memory.application.profile_extractor import ExtractedProfileItem, ProfileExtractor
from modules.memory.application.supersede import SupersedeDetector
from modules.memory.infra.vector_store import MemoryStore, _compute_content_hash

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PostResponseContext:
    """对话提交后的后处理上下文。"""

    session_id: str
    user_input: str
    assistant_output: str
    tool_trace: list[dict] = field(default_factory=list)
    protected_memory_ids: list[str] = field(default_factory=list)


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
        profile_extractor: ProfileExtractor | None = None,
        markdown_store: MarkdownStore | None = None,
    ) -> None:
        self.store = store
        self.memorizer = memorizer
        self.supersede_detector = supersede_detector or SupersedeDetector(store)
        self.profile_extractor = profile_extractor or ProfileExtractor()
        self.markdown_store = markdown_store

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
        protected_hashes = {
            (item.memory_type, item.content_hash)
            for item in self.store.search_by_ids(memorized_ids)
        }

        # spec 4c-4e: 检测用户否定并执行 supersede
        if ctx.user_input:
            superseded = self.supersede_detector.process_supersede(ctx.user_input)
            result.superseded_count = len(superseded)

        # 执行规则需要立即生效；用户画像由 consolidation 统一归档。
        implicit_count = self._extract_immediate_procedures(ctx, protected_hashes)

        result.extracted_memories = len(memorized_ids) + implicit_count
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
        protected_ids: list[str],
    ) -> list[str]:
        """从 tool_trace 中提取 memorize 工具写入的记忆 ID（spec 4b）。

        这些 ID 被标记为受保护，后续 supersede 检测不会误删它们。
        """
        memorized_ids: list[str] = []
        protected_set = set(protected_ids)

        for call in tool_trace:
            tool_name = (
                call.get("tool", "")
                or call.get("name", "")
                or call.get("function", {}).get("name", "")
            )
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

            # 检查是否已被保护。
            content_hash = _compute_content_hash(summary, memory_type)
            existing = self.store.search_by_source_ref(
                f"memorize_tool:{memory_type}:{summary[:40]}"
            )
            for item in existing:
                if item.content_hash == content_hash:
                    memorized_ids.append(item.id)
                    protected_set.add(item.id)

        return memorized_ids

    def _extract_immediate_procedures(
        self,
        ctx: PostResponseContext,
        protected_hashes: set[tuple[str, str]] | None = None,
    ) -> int:
        """仅从对话中提取需要立即生效的执行规则。

        身份、偏好、需求和任务先写入 PENDING.md，
        由定时画像归档器批量合并，避免每轮改变长期提示词。
        """
        if not ctx.user_input:
            return 0

        extracted = 0
        skip_hashes = protected_hashes or set()
        for item in self.profile_extractor.extract_memory_items(ctx.user_input):
            if item.memory_type != "procedure":
                continue
            try:
                content_hash = _compute_content_hash(item.summary, item.memory_type)
                if (item.memory_type, content_hash) in skip_hashes:
                    continue
                self.memorizer.memorize(
                    memory_type=item.memory_type,
                    summary=item.summary,
                    source_ref=self._build_auto_source_ref(ctx.session_id, item),
                    emotional_weight=item.emotional_weight,
                )
                self._sync_markdown_item(item)
                extracted += 1
                logger.debug(
                    "自动提取 %s 记忆: %s",
                    item.memory_type,
                    item.summary[:40],
                )
            except Exception:
                logger.exception("隐含记忆抽取失败")
        return extracted

    def _build_auto_source_ref(
        self,
        session_id: str,
        item: ExtractedProfileItem,
    ) -> str:
        """生成稳定来源标识，便于 undo 和调试定位自动写入。"""
        digest = _compute_content_hash(item.summary, item.memory_type)
        return f"auto:{item.source_label}:{session_id}:{digest}"

    def _sync_markdown_item(self, item: ExtractedProfileItem) -> None:
        """把自动抽取结果同步到人类可读的 Markdown 记忆层。"""
        if self.markdown_store is None:
            return
        try:
            self.markdown_store.append_memory_item(
                item.memory_type,
                item.summary,
                source_label=item.source_label,
            )
        except Exception:
            logger.exception("Markdown 记忆同步失败")
