"""测试主动回复插件模块系统。"""

import asyncio
import pytest

from flow_agent.proactive.modules import (
    ModuleManager,
    ModuleContext,
    create_module_factory,
    GateModule,
    FetchModule,
    JudgeModule,
    ResolveModule,
    DeliverModule,
)


@pytest.mark.asyncio
async def test_module_lifecycle():
    """测试模块生命周期。"""
    # 创建模块
    gate = GateModule(max_per_day=5)
    
    # 创建上下文
    context = ModuleContext(
        chat_id="test_chat",
        is_busy=False,
        base_score=0.5,
    )
    
    # 测试初始化
    assert not gate.is_active()
    await gate.initialize(context)
    
    # 测试启动
    await gate.start(context)
    assert gate.is_active()
    
    # 测试停止
    await gate.stop(context)
    assert not gate.is_active()
    
    # 测试清理
    await gate.cleanup(context)


@pytest.mark.asyncio
async def test_module_manager():
    """测试模块管理器。"""
    manager = ModuleManager()
    
    # 创建模块
    gate = GateModule(max_per_day=5)
    fetch = FetchModule()
    judge = JudgeModule()
    resolve = ResolveModule()
    deliver = DeliverModule()
    
    # 注册模块
    manager.register_module(gate)
    manager.register_module(fetch)
    manager.register_module(judge)
    manager.register_module(resolve)
    manager.register_module(deliver)
    
    # 检查执行顺序
    order = manager.get_execution_order()
    assert len(order) == 5
    assert "gate" in order
    assert "fetch" in order
    assert "judge" in order
    assert "resolve" in order
    assert "deliver" in order
    
    # 检查依赖关系
    assert order.index("gate") < order.index("fetch")
    assert order.index("fetch") < order.index("judge")
    assert order.index("judge") < order.index("resolve")
    assert order.index("resolve") < order.index("deliver")


@pytest.mark.asyncio
async def test_module_execution():
    """测试模块执行。"""
    manager = ModuleManager()
    
    # 创建并注册模块
    gate = GateModule(max_per_day=5)
    fetch = FetchModule()
    manager.register_module(gate)
    manager.register_module(fetch)
    
    # 创建上下文
    context = ModuleContext(
        chat_id="test_chat",
        is_busy=False,
        base_score=0.5,
    )
    
    # 初始化和启动模块
    await manager.initialize_all(context)
    await manager.start_all(context)
    
    # 执行管道
    result_context = await manager.execute_pipeline(context)
    
    # 验证结果
    assert result_context.gate_passed
    assert result_context.gate_reason == "ok"
    
    # 清理
    await manager.stop_all(context)
    await manager.cleanup_all(context)


@pytest.mark.asyncio
async def test_module_factory():
    """测试模块工厂。"""
    factory = create_module_factory()
    
    # 创建模块
    gate = factory.create_gate_module(max_per_day=10)
    fetch = factory.create_fetch_module()
    judge = factory.create_judge_module()
    resolve = factory.create_resolve_module()
    deliver = factory.create_deliver_module()
    
    # 验证模块类型
    assert isinstance(gate, GateModule)
    assert isinstance(fetch, FetchModule)
    assert isinstance(judge, JudgeModule)
    assert isinstance(resolve, ResolveModule)
    assert isinstance(deliver, DeliverModule)
    
    # 测试构建默认管道
    manager = ModuleManager()
    factory.build_default_pipeline(manager)
    
    # 验证模块注册
    assert len(manager.get_all_modules()) == 5


@pytest.mark.asyncio
async def test_module_context():
    """测试模块上下文。"""
    context = ModuleContext(
        chat_id="test_chat",
        is_busy=False,
        base_score=0.5,
    )
    
    # 测试元数据更新
    updated = context.with_metadata(gate_passed=True, gate_reason="test")
    assert updated.gate_passed
    assert updated.gate_reason == "test"
    
    # 测试共享数据
    context.set_slot("test_key", "test_value")
    assert context.get_slot("test_key") == "test_value"
    
    # 测试共享数据更新
    updated = context.with_shared_data(new_key="new_value")
    assert updated.get_slot("new_key") == "new_value"
    assert updated.get_slot("test_key") == "test_value"


if __name__ == "__main__":
    # 简单测试运行
    async def run_tests():
        print("测试模块生命周期...")
        await test_module_lifecycle()
        print("✓ 模块生命周期测试通过")
        
        print("测试模块管理器...")
        await test_module_manager()
        print("✓ 模块管理器测试通过")
        
        print("测试模块执行...")
        await test_module_execution()
        print("✓ 模块执行测试通过")
        
        print("测试模块工厂...")
        await test_module_factory()
        print("✓ 模块工厂测试通过")
        
        print("测试模块上下文...")
        await test_module_context()
        print("✓ 模块上下文测试通过")
        
        print("\n所有测试通过！")
    
    asyncio.run(run_tests())
