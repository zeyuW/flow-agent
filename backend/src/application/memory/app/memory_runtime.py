"""记忆运行时：统一双层记忆架构并绑定事件总线。"""

import logging
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from application.memory.infra.embedder import OpenAIEmbedder
from application.memory.infra.markdown_store import MarkdownStore
from application.memory.app.engine import MemoryEngine
from application.memory.infra.retriever import DualChannelRetriever
from application.memory.app.memorizer import Memorizer
from application.memory.app.post_response import PostResponseMemoryWorker
from application.memory.app.supersede import SupersedeDetector
from application.memory.infra.vector_store import MemoryStore
from application.memory.app.query_rewriter import QueryRewriter
from application.memory.app.dedup import DedupDecider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryRuntime:
    """记忆运行时，包含双层记忆架构。

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
    query_rewriter: QueryRewriter | None = None
    dedup_decider: DedupDecider | None = None
    event_executor: Executor | None = None


def build_memory_runtime(
    data_dir: Path,
    *,
    memory_dir: Path | None = None,
    vector_db_path: Path | None = None,
    embedding_cache_path: Path | None = None,
    api_key: str = "",
    base_url: str | None = None,
    embedding_model: str = "text-embedding-3-small",
    llm_client: Any = None,
    llm_model: str = "",
) -> MemoryRuntime:
    """构建包含所有组件的记忆运行时。

    Args:
        data_dir: 数据目录（如 .flow/data/）。
        memory_dir: Markdown 记忆目录。
        vector_db_path: 向量记忆数据库路径。
        embedding_cache_path: 向量化缓存路径。
        api_key: OpenAI API key。
        base_url: OpenAI API base URL。
        embedding_model: Embedding 模型名称。
        llm_client: 用于 QueryRewriter 和 DedupDecider 的可选 LLM 客户端。
        llm_model: QueryRewriter 和 DedupDecider 的 LLM 模型名称。

    Returns:
        包含所有记忆组件的 MemoryRuntime 实例。
    """
    # 构建 Markdown 记忆层
    resolved_memory_dir = memory_dir or (data_dir / "memory")
    markdown_store = MarkdownStore(root=resolved_memory_dir)
    markdown_store.initialize()
    logger.info("markdown memory layer initialized at %s", resolved_memory_dir)

    # 初始化向量存储和检索组件
    resolved_vector_db = vector_db_path or (data_dir / "memory_vectors.db")
    vector_store = MemoryStore(db_path=resolved_vector_db)
    logger.info("vector store initialized at %s", resolved_vector_db)

    # 向量化器
    embedder = OpenAIEmbedder(
        api_key=api_key,
        base_url=base_url,
        model=embedding_model,
        cache_path=embedding_cache_path or (data_dir / "embedding_cache.json"),
    )

    # 记忆写入器
    memorizer = Memorizer(store=vector_store, embedder=embedder)

    # 双通道检索器
    retriever = DualChannelRetriever(store=vector_store, embedder=embedder)

    # 记忆引擎
    engine = MemoryEngine(
        store=vector_store,
        embedder=embedder,
        retriever=retriever,
    )

    # 失效替换检测器
    supersede_detector = SupersedeDetector(store=vector_store)

    # 回复后记忆处理器
    post_response_worker = PostResponseMemoryWorker(
        store=vector_store,
        memorizer=memorizer,
        supersede_detector=supersede_detector,
        markdown_store=markdown_store,
    )

    # 可选的高级组件
    query_rewriter = None
    dedup_decider = None

    if llm_client:
        query_rewriter = QueryRewriter(
            llm_client=llm_client,
            model=llm_model,
        )
        logger.info("query rewriter initialized with model: %s", llm_model)

        dedup_decider = DedupDecider(
            store=vector_store,
            embedder=embedder,
            llm_client=llm_client,
            model=llm_model,
        )
        logger.info("dedup decider initialized with model: %s", llm_model)

    runtime = MemoryRuntime(
        markdown_store=markdown_store,
        vector_store=vector_store,
        embedder=embedder,
        memorizer=memorizer,
        retriever=retriever,
        engine=engine,
        supersede_detector=supersede_detector,
        post_response_worker=post_response_worker,
        query_rewriter=query_rewriter,
        dedup_decider=dedup_decider,
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
    consolidator=None,
    executor: Executor | None = None,
) -> None:
    """绑定记忆相关事件（spec 1e）。

    订阅 TurnCommitted 事件，在对话提交后自动触发：
    - 立即生效的规则记忆处理
    - 近期上下文刷新与对话 consolidation

    Args:
        runtime: 记忆运行时实例。
        event_bus: EventBus 实例。
        consolidator: 可选的回合后对话归档器。
    """
    from infra.bus.event import EventSubscriber, TurnCommitted

    memory_executor = executor or ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="memory-events",
    )
    runtime.event_executor = memory_executor

    class MemoryEventSubscriber:
        """记忆事件订阅者：监听 TurnCommitted 事件并异步处理。"""

        def __init__(self, rt: MemoryRuntime) -> None:
            self.rt = rt

        def on_event(self, event) -> None:
            if not isinstance(event, TurnCommitted):
                return

            try:
                future = memory_executor.submit(self._process, event)
                future.add_done_callback(self._log_failure)
            except Exception:
                logger.exception("记忆事件入队失败")

        def _process(self, event: TurnCommitted) -> None:
            """在后台串行处理记忆更新，不能阻塞回复投递。"""

            session_id = event.session_id or "default"
            user_input = event.user_input or ""
            assistant_output = event.assistant_output or ""
            tool_trace = event.tool_trace or []

            # 立即生效的规则记忆处理。
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

            if consolidator is not None:
                try:
                    maintenance_result = consolidator.on_turn_committed(session_id)
                    logger.debug(
                        "memory consolidation: consolidated=%s history=%d pending=%d",
                        maintenance_result.consolidated,
                        maintenance_result.history_count,
                        maintenance_result.pending_count,
                    )
                except Exception:
                    logger.exception("memory consolidation failed")

        @staticmethod
        def _log_failure(future) -> None:
            try:
                future.result()
            except Exception:
                logger.exception("后台记忆事件处理失败")

    subscriber = MemoryEventSubscriber(runtime)
    event_bus.subscribe(subscriber)
    logger.info("memory events wired to event bus (subscribed to TurnCommitted)")
