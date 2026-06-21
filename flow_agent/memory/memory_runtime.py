"""记忆运行时：统一构建双层记忆架构并绑定事件总线。

实现 spec 1a-1e：
- 1a: build_memory_runtime() 统一构建入口
- 1b: Markdown 记忆层初始化
- 1c: 插件引擎层加载（通过工具系统）
- 1d: 向量存储和检索组件初始化
- 1e: 绑定 TurnCommitted 等事件
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from flow_agent.memory.embedder import OpenAIEmbedder
from flow_agent.memory.markdown_store import MarkdownStore
from flow_agent.memory.memory_engine import MemoryEngine
from flow_agent.memory.memory_retriever import DualChannelRetriever
from flow_agent.memory.memorizer import Memorizer
from flow_agent.memory.post_response import PostResponseMemoryWorker
from flow_agent.memory.supersede import SupersedeDetector
from flow_agent.memory.vector_store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryRuntime:
    """记忆运行时：包含双层记忆的所有核心组件。

    两层架构：
    - Markdown 层：人类可读的 MEMORY.md / HISTORY.md / RECENT_CONTEXT.md
    - 向量引擎层：SQLite 向量存储 + 双通道检索 + 后处理
    """

    markdown_store: MarkdownStore
    vector_store: MemoryStore
    embedder: OpenAIEmbedder
    memorizer: Memorizer
    retriever: DualChannelRetriever
    engine: MemoryEngine
    supersede_detector: SupersedeDetector
    post_response_worker: PostResponseMemoryWorker


def build_memory_runtime(
    data_dir: Path,
    *,
    api_key: str = "",
    base_url: str | None = None,
    embedding_model: str = "text-embedding-3-small",
) -> MemoryRuntime:
    """构建记忆运行时（spec 1a）。

    统一构建 Markdown 层和向量引擎层的所有组件。

    Args:
        data_dir: 数据目录（如 .flow/data/）。
        api_key: OpenAI API key。
        base_url: OpenAI API base URL。
        embedding_model: embedding 模型名称。

    Returns:
        MemoryRuntime 实例，包含所有记忆组件。
    """
    # spec 1b: 构建 Markdown 记忆层
    memory_dir = data_dir / "memory"
    markdown_store = MarkdownStore(root=memory_dir)
    markdown_store.initialize()
    logger.info("markdown memory layer initialized at %s", memory_dir)

    # spec 1d: 初始化向量存储和检索组件
    vector_db_path = data_dir / "memory_vectors.db"
    vector_store = MemoryStore(db_path=vector_db_path)
    logger.info("vector store initialized at %s", vector_db_path)

    # Embedder
    embedder = OpenAIEmbedder(
        api_key=api_key,
        base_url=base_url,
        model=embedding_model,
        cache_path=data_dir / "embedding_cache.json",
    )

    # Memorizer
    memorizer = Memorizer(store=vector_store, embedder=embedder)

    # 双通道检索器
    retriever = DualChannelRetriever(store=vector_store, embedder=embedder)

    # 记忆引擎
    engine = MemoryEngine(
        store=vector_store,
        embedder=embedder,
        retriever=retriever,
    )

    # Supersede 检测器
    supersede_detector = SupersedeDetector(store=vector_store)

    # Post-response 后处理 Worker
    post_response_worker = PostResponseMemoryWorker(
        store=vector_store,
        memorizer=memorizer,
        supersede_detector=supersede_detector,
    )

    runtime = MemoryRuntime(
        markdown_store=markdown_store,
        vector_store=vector_store,
        embedder=embedder,
        memorizer=memorizer,
        retriever=retriever,
        engine=engine,
        supersede_detector=supersede_detector,
        post_response_worker=post_response_worker,
    )

    active_count = vector_store.count_active()
    logger.info(
        "memory runtime built: %d active memories, embedding dim=%d",
        active_count,
        embedder.dimension,
    )

    return runtime


def wire_memory_events(
    runtime: MemoryRuntime,
    event_bus,
) -> None:
    """绑定记忆相关事件（spec 1e）。

    订阅 TurnCommitted 事件，在对话提交后自动触发：
    - 记忆后处理（supersede 检测 + 隐式记忆提取）
    - Markdown 层更新（事件记录 + 近期上下文更新）

    Args:
        runtime: 记忆运行时实例。
        event_bus: EventBus 实例。
    """
    from flow_agent.messaging.event_bus import EventSubscriber, TurnCommitted

    class MemoryEventSubscriber:
        """记忆事件订阅者：监听 TurnCommitted 事件。"""

        def __init__(self, rt: MemoryRuntime) -> None:
            self.rt = rt

        def on_event(self, event) -> None:
            if not isinstance(event, TurnCommitted):
                return

            session_id = event.session_id or "default"
            user_input = event.user_input or ""
            assistant_output = event.assistant_output or ""
            tool_trace = event.tool_trace or []

            # 后处理记忆（spec 4a）
            try:
                result = self.rt.post_response_worker.on_turn_committed(
                    session_id=session_id,
                    user_input=user_input,
                    assistant_output=assistant_output,
                    tool_trace=tool_trace,
                )
                logger.debug(
                    "post-response memory: extracted=%d superseded=%d",
                    result.extracted_memories,
                    result.superseded_count,
                )
            except Exception:
                logger.exception("post-response memory processing failed")

            # 更新 Markdown 事件记录
            try:
                if assistant_output:
                    summary = assistant_output[:120].replace("\n", " ")
                    self.rt.markdown_store.append_event(
                        f"对话回复: {summary}",
                    )
            except Exception:
                logger.exception("markdown event append failed")

    subscriber = MemoryEventSubscriber(runtime)
    event_bus.subscribe(subscriber)
    logger.info("memory events wired to event bus (subscribed to TurnCommitted)")
