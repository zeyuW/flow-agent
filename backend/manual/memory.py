"""手动测试记忆系统的脚本。"""

import asyncio
import sys
import numpy as np
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from flow_agent.memory.vector_store import MemoryStore
from flow_agent.memory.embedder import OpenAIEmbedder
from flow_agent.memory.query_rewriter import QueryRewriter
from flow_agent.memory.dedup_decider import DedupDecider


def test_vector_store():
    """测试向量存储和检索。"""
    print("=== 测试向量存储 ===")
    
    # 创建测试数据库
    db_path = Path("/tmp/test_memory_manual.db")
    if db_path.exists():
        db_path.unlink()
    
    store = MemoryStore(db_path)
    print(f"✓ 向量存储初始化成功，sqlite-vec: {store._vec_enabled}")
    
    # 测试写入
    test_embedding = np.random.rand(1024).tolist()
    item = store.write(
        memory_type="test",
        summary="这是一个测试记忆条目",
        embedding=test_embedding,
        source_ref="test_source"
    )
    print(f"✓ 写入记忆条目: ID={item.id}, 类型={item.memory_type}")
    
    # 测试检索
    results = store.vector_search(test_embedding, top_k=1)
    print(f"✓ 向量搜索结果: {len(results)} 条")
    if results:
        print(f"  - 相似度: {results[0][1]:.4f}")
    
    # 测试去重
    item2 = store.write(
        memory_type="test",
        summary="这是一个测试记忆条目",  # 相同内容
        embedding=test_embedding,
        source_ref="test_source"
    )
    print(f"✓ 去重测试: reinforcement={item2.reinforcement} (应为 2)")
    
    # 测试 consolidation event
    result = store.upsert_consolidation_event(
        source_ref="test_consolidation",
        summary="这是一个 consolidation 事件",
        embedding=test_embedding
    )
    print(f"✓ consolidation event: {result}")
    
    # 测试检查 consolidation
    has_consolidation = store.has_consolidation_source_ref("test_consolidation")
    print(f"✓ 检查 consolidation: {has_consolidation} (应为 True)")
    
    # 清理
    store.close()
    db_path.unlink()
    print("✓ 测试完成，清理临时文件\n")


async def test_query_rewriter():
    """测试查询重写器。"""
    print("=== 测试查询重写器 ===")
    
    # 模拟 LLM 客户端
    class MockLLMClient:
        async def chat(self, messages, model, max_tokens):
            class MockResponse:
                content = '{"query": "用户询问关于记忆系统的问题", "needs_search": true}'
            return MockResponse()
    
    rewriter = QueryRewriter(
        llm_client=MockLLMClient(),
        model="test-model"
    )
    
    decision = await rewriter.decide(
        user_msg="记忆系统怎么用？",
        recent_history="用户之前问过关于配置的问题"
    )
    
    print(f"✓ 查询重写结果:")
    print(f"  - 需要情节性检索: {decision.needs_episodic}")
    print(f"  - 重写后查询: {decision.episodic_query}")
    print(f"  - 延迟: {decision.latency_ms}ms")
    print()


async def test_dedup_decider():
    """测试去重决策器。"""
    print("=== 测试去重决策器 ===")
    
    # 创建测试存储
    db_path = Path("/tmp/test_dedup_manual.db")
    if db_path.exists():
        db_path.unlink()
    
    store = MemoryStore(db_path)
    
    # 模拟 embedder
    class MockEmbedder:
        async def embed(self, text):
            return np.random.rand(1024).tolist()
    
    # 模拟 LLM 客户端
    class MockLLMClient:
        async def chat(self, messages, model, max_tokens):
            class MockResponse:
                content = '{"decision": "create", "actions": []}'
            return MockResponse()
    
    decider = DedupDecider(
        store=store,
        embedder=MockEmbedder(),
        llm_client=MockLLMClient(),
        model="test-model"
    )
    
    # 测试去重决策
    result = await decider.decide({
        "summary": "这是一个新的记忆条目",
        "memory_type": "test",
        "source_ref": "test_source"
    })
    
    print(f"✓ 去重决策结果:")
    print(f"  - 决策: {result.decision}")
    print(f"  - 相似项数量: {len(result.similar_items)}")
    
    # 清理
    db_path.unlink()
    print("✓ 测试完成，清理临时文件\n")


def test_integration():
    """集成测试：完整的记忆写入和检索流程。"""
    print("=== 集成测试 ===")
    
    db_path = Path("/tmp/test_integration.db")
    if db_path.exists():
        db_path.unlink()
    
    store = MemoryStore(db_path)
    print(f"✓ 创建向量存储: {store._vec_enabled}")
    
    # 写入多条记忆
    memories = [
        ("用户喜欢编程", "preference"),
        ("用户昨天学习了 Python", "event"),
        ("用户计划学习机器学习", "goal"),
    ]
    
    for summary, mtype in memories:
        embedding = np.random.rand(1024).tolist()
        item = store.write(
            memory_type=mtype,
            summary=summary,
            embedding=embedding,
            source_ref="integration_test"
        )
        print(f"✓ 写入: {summary} (类型: {mtype}, ID: {item.id})")
    
    # 测试检索
    query_embedding = np.random.rand(1024).tolist()
    results = store.vector_search(query_embedding, top_k=3)
    print(f"✓ 检索到 {len(results)} 条记忆")
    
    # 统计
    active_count = store.count_active()
    print(f"✓ 活跃记忆总数: {active_count}")
    
    # 测试 memory replacements
    active_items = store.list_active()[:2]
    old_items = [item.to_dict() for item in active_items]
    new_item = {
        "id": "test_new_id",
        "memory_type": "preference",
        "summary": "用户喜欢深度学习",
        "source_ref": "integration_test",
        "happened_at": "",
        "extra_json": {}
    }
    replacement_count = store.record_replacements(
        old_items=old_items,
        new_item=new_item,
        source_ref="integration_test"
    )
    print(f"✓ 记录了 {replacement_count} 条替换关系")
    
    # 列出替换关系
    replacements = store.list_replacements()
    print(f"✓ 替换关系总数: {len(replacements)}")
    
    # 清理
    store.close()
    db_path.unlink()
    print("✓ 集成测试完成\n")


def main():
    """运行所有测试。"""
    print("开始手动测试记忆系统...\n")
    
    # 测试向量存储
    test_vector_store()
    
    # 测试查询重写器
    asyncio.run(test_query_rewriter())
    
    # 测试去重决策器
    asyncio.run(test_dedup_decider())
    
    # 集成测试
    test_integration()
    
    print("所有测试完成！")


if __name__ == "__main__":
    main()
