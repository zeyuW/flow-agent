"""FlowAgent 记忆模块：双层长期记忆架构。

Markdown 层（人类可读）：
- markdown_store: MEMORY.md / HISTORY.md / RECENT_CONTEXT.md 文件管理
- consolidation: 对话归档压缩

向量引擎层（语义检索）：
- vector_store: SQLite 向量存储 + content_hash 去重 + supersede
- embedder: OpenAI embeddings API + hash fallback
- memorizer: embedding 写入 + 去重强化
- memory_retriever: 双通道（向量 + 关键词）+ RRF 融合
- memory_engine: 查询路由 + 检索执行
- injection: 提示词注入块构建
- supersede: 失效检测（否定/纠错意图）
- post_response: 对话提交后异步记忆处理
- memory_runtime: 统一构建入口 + 事件绑定
"""
