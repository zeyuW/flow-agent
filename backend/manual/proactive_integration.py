#!/usr/bin/env python3
"""主动推送功能集成测试"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.proactive.runtime import build_proactive_runtime
from flow_agent.proactive.mcp_pool import McpClientPool

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MockLLMClient:
    """模拟 LLM 客户端"""
    
    def generate(self, messages, tools=None):
        """模拟 LLM 生成响应"""
        # 简单返回一个决策
        class MockResponse:
            def __init__(self):
                self.content = "我决定推送这条消息"
                self.tool_calls = [
                    type('ToolCall', (), {
                        'id': 'call_1',
                        'name': 'mark_interesting',
                        'arguments': {'item_id': '0', 'reason': '测试内容'}
                    }),
                    type('ToolCall', (), {
                        'id': 'call_2',
                        'name': 'message_push',
                        'arguments': {'text': '这是一条测试主动推送的消息'}
                    }),
                    type('ToolCall', (), {
                        'id': 'call_3',
                        'name': 'finish_turn',
                        'arguments': {'decision': 'reply'}
                    })
                ]
        
        return MockResponse()


class MockMemoryEngine:
    """模拟记忆引擎"""
    
    def retrieve_for_prompt(self, query):
        return f"记忆检索结果: {query}"


class MockOutboundPort:
    """模拟输出端口"""
    
    def __init__(self):
        self.messages = []
    
    def send(self, dispatch):
        self.messages.append(dispatch)
        logger.info(f"消息已发送到 {dispatch.channel}: {dispatch.text}")


async def test_proactive_integration():
    """测试主动推送集成"""
    
    logger.info("=" * 60)
    logger.info("开始主动推送集成测试")
    logger.info("=" * 60)
    
    # 1. 启动模拟 MCP server
    logger.info("步骤 1: 启动模拟 MCP server")
    mcp_server_path = Path(__file__).parent.parent / ".flow/plugins/test_proactive/mcp_server.py"
    mcp_process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(mcp_server_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    logger.info(f"MCP server 进程已启动 (pid={mcp_process.pid})")
    
    # 等待 MCP server 启动
    await asyncio.sleep(2)
    
    try:
        # 2. 加载测试插件
        logger.info("步骤 2: 加载测试插件")
        plugins_dir = Path(__file__).parent.parent / ".flow/plugins"
        plugin_manager = PluginManager(
            plugins_dir=plugins_dir,
            workspace=Path(__file__).parent.parent / ".flow"
        )
        await plugin_manager.load_all()
        
        # 获取主动推送数据源
        proactive_sources = plugin_manager.get_proactive_sources()
        logger.info(f"已加载 {len(proactive_sources)} 个插件的主动推送数据源")
        for plugin_id, sources in proactive_sources.items():
            logger.info(f"  插件 {plugin_id}: {len(sources)} 个数据源")
            for source in sources:
                logger.info(f"    - {source.spec.id}: {source.spec.channels}")
        
        # 3. 构建 MCP 连接池
        logger.info("步骤 3: 构建 MCP 连接池")
        mcp_pool = McpClientPool()
        mcp_pool.add_server(
            name="test_mcp_server",
            command=[sys.executable, str(mcp_server_path)]
        )
        
        # 4. 构建主动推送运行时
        logger.info("步骤 4: 构建主动推送运行时")
        mock_llm = MockLLMClient()
        mock_memory = MockMemoryEngine()
        mock_outbound = MockOutboundPort()

        # 先测试 MCP 连接
        logger.info("测试 MCP 连接...")
        test_pool = McpClientPool()
        test_pool.add_server(
            name="test_mcp_server",
            command=[sys.executable, str(mcp_server_path)]
        )
        await test_pool.connect_all()
        logger.info(f"MCP 连接完成，客户端数量: {len(test_pool._clients)}")

        # 测试 MCP 调用
        test_result = await test_pool.call("test_mcp_server", "get_proactive_events", {})
        logger.info(f"MCP 测试调用结果: {test_result}")
        await test_pool.close_all()

        runtime = build_proactive_runtime(
            chat_id="test_user",
            llm_client=mock_llm,
            memory_engine=mock_memory,
            session_manager=None,
            outbound_port=mock_outbound,
            mcp_servers=[
                {
                    "name": "test_mcp_server",
                    "command": [sys.executable, str(mcp_server_path)]
                }
            ],
            proactive_sources=proactive_sources,
            max_per_day=100,  # 测试用，提高限制
            min_interval=10,  # 测试用，缩短间隔
            max_interval=30,
            cooldown=0,  # 测试用，禁用冷却
            hawkes_enabled=True,
            hawkes_base_intensity=0.1,
            hawkes_excitation_alpha=0.5,
            hawkes_decay_beta=0.1,
            hawkes_time_constant=60.0,
        )

        logger.info("主动推送运行时构建完成")

        # 检查 DataGateway 的配置
        logger.info(f"DataGateway 配置检查:")
        logger.info(f"  通道映射: {runtime._pipeline._gateway._channel_servers}")
        logger.info(f"  数据源数量: {len(runtime._pipeline._gateway._proactive_sources)}")

        # 连接 runtime 的 MCP 连接池
        logger.info("连接 runtime 的 MCP 连接池...")
        await runtime._pool.connect_all()
        logger.info(f"Runtime MCP 连接池客户端数量: {len(runtime._pool._clients)}")

        # 5. 运行主动推送循环（单次 tick）
        logger.info("步骤 5: 运行主动推送循环（单次 tick）")

        # 直接运行 pipeline 的单次 tick
        tick = await runtime._pipeline.run(
            chat_id="test_user",
            base_score=0.5,  # 设置较高的 base_score 以通过 Gate
            is_busy=False
        )
        
        logger.info("Tick 执行完成")
        logger.info(f"  Gate 结果: {tick.gate_result}")
        logger.info(f"  Gateway 结果: {len(tick.gateway_result.all_items)} 个项目")
        logger.info(f"  Judge 结果: {tick.judge_result.decision}")
        logger.info(f"  Resolve 结果: {tick.resolve_result.decision}")
        logger.info(f"  Deliver 结果: {tick.deliver_result.sent if tick.deliver_result else 'N/A'}")
        
        # 6. 验证结果
        logger.info("步骤 6: 验证结果")
        
        success = True
        
        # 检查 Gate 是否通过
        if not tick.gate_result.passed:
            logger.error(f"Gate 未通过: {tick.gate_result}")
            success = False
        else:
            logger.info("✓ Gate 通过")
        
        # 检查是否获取到数据
        if len(tick.gateway_result.all_items) == 0:
            logger.error("未获取到任何数据")
            success = False
        else:
            logger.info(f"✓ 获取到 {len(tick.gateway_result.all_items)} 个数据项")
        
        # 检查 Judge 决策
        if tick.judge_result.decision != "reply":
            logger.warning(f"Judge 决策为 {tick.judge_result.decision}，预期 reply")
        else:
            logger.info(f"✓ Judge 决策为 reply")
        
        # 检查是否发送消息
        if tick.deliver_result and tick.deliver_result.sent:
            logger.info(f"✓ 消息已发送: {tick.deliver_result.message}")
        else:
            logger.warning("消息未发送")
        
        # 检查输出端口
        if mock_outbound.messages:
            logger.info(f"✓ 输出端口收到 {len(mock_outbound.messages)} 条消息")
            for msg in mock_outbound.messages:
                logger.info(f"  - {msg.channel}: {msg.text}")
        else:
            logger.warning("输出端口未收到消息")
        
        # 7. 清理
        logger.info("步骤 7: 清理资源")
        await runtime.stop()
        
        # 等待 ACK 异步任务完成
        await asyncio.sleep(2)
        
        # 终止 MCP server
        mcp_process.terminate()
        try:
            await asyncio.wait_for(mcp_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            mcp_process.kill()
            await mcp_process.wait()
        
        logger.info("MCP server 已终止")
        
        # 总结
        logger.info("=" * 60)
        if success:
            logger.info("✓ 主动推送集成测试通过")
        else:
            logger.error("✗ 主动推送集成测试失败")
        logger.info("=" * 60)
        
        return success
        
    except Exception as e:
        logger.exception("测试过程中发生异常")
        
        # 清理
        if 'runtime' in locals():
            await runtime.stop()
        if 'mcp_process' in locals():
            mcp_process.terminate()
            try:
                await asyncio.wait_for(mcp_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                mcp_process.kill()
                await mcp_process.wait()
        
        return False


if __name__ == "__main__":
    result = asyncio.run(test_proactive_integration())
    sys.exit(0 if result else 1)
