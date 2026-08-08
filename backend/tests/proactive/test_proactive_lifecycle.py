"""主动模块生命周期编译测试。"""

import asyncio

import pytest

from application.proactive.app.lifecycle import ProactiveLifecycle, compile_proactive_lifecycle


class _Module:
    """测试用声明式主动模块。"""

    def __init__(
        self,
        slot: str,
        *,
        requires: tuple[str, ...] = (),
        produces: tuple[str, ...] = (),
        events: list[str] | None = None,
    ) -> None:
        self.slot = slot
        self.requires = requires
        self.produces = produces
        self.events = events if events is not None else []

    async def run(self, context):
        self.events.append(f"run:{self.slot}")
        return context


def test_compiler_orders_modules_from_produced_data_dependency():
    """消费者必须在其所需数据的生产者之后运行。"""

    events: list[str] = []
    consumer = _Module(
        "consumer",
        requires=("proactive:items",),
        events=events,
    )
    producer = _Module(
        "producer",
        produces=("proactive:items",),
        events=events,
    )

    lifecycle = compile_proactive_lifecycle([consumer, producer])

    assert isinstance(lifecycle, ProactiveLifecycle)
    assert lifecycle.slots == ("producer", "consumer")


def test_compiler_rejects_missing_data_dependency():
    """未声明初始来源的数据依赖必须在启动前失败。"""

    module = _Module("consumer", requires=("proactive:missing",))

    with pytest.raises(ValueError, match="数据依赖不存在"):
        compile_proactive_lifecycle([module])


def test_compiler_rejects_duplicate_data_producers():
    """同一数据槽只能由一个模块生产，避免执行结果依赖加载顺序。"""

    with pytest.raises(ValueError, match="重复生产者"):
        compile_proactive_lifecycle(
            [
                _Module("first", produces=("proactive:items",)),
                _Module("second", produces=("proactive:items",)),
            ]
        )


def test_compiler_rejects_cyclic_module_dependencies():
    """互相依赖的模块不能形成可运行的主动 tick。"""

    with pytest.raises(ValueError, match="存在循环"):
        compile_proactive_lifecycle(
            [
                _Module("first", requires=("second",)),
                _Module("second", requires=("first",)),
            ]
        )


def test_lifecycle_rolls_back_started_modules_when_start_fails():
    """启动失败时必须逆序停止已启动模块。"""

    events: list[str] = []

    class StartedModule(_Module):
        async def start(self):
            events.append("start:first")

        async def stop(self):
            events.append("stop:first")

    class FailingModule(_Module):
        async def start(self):
            events.append("start:second")
            raise RuntimeError("启动失败")

        async def stop(self):
            events.append("stop:second")

    lifecycle = compile_proactive_lifecycle(
        [StartedModule("first"), FailingModule("second")]
    )

    with pytest.raises(RuntimeError, match="启动失败"):
        asyncio.run(lifecycle.start())

    assert events == [
        "start:first",
        "start:second",
        "stop:second",
        "stop:first",
    ]


def test_lifecycle_stops_started_modules_in_reverse_order():
    """正常关闭也必须按依赖反向顺序释放资源。"""

    events: list[str] = []

    class StartedModule(_Module):
        async def start(self):
            events.append(f"start:{self.slot}")

        async def stop(self):
            events.append(f"stop:{self.slot}")

    lifecycle = compile_proactive_lifecycle(
        [StartedModule("first"), StartedModule("second")]
    )

    async def scenario():
        await lifecycle.start()
        await lifecycle.stop()

    asyncio.run(scenario())

    assert events == ["start:first", "start:second", "stop:second", "stop:first"]


def test_lifecycle_preserves_start_error_when_rollback_stop_fails():
    """回滚异常不得替代触发回滚的启动异常。"""

    class BrokenStopModule(_Module):
        async def start(self):
            return None

        async def stop(self):
            raise RuntimeError("停止失败")

    class BrokenStartModule(_Module):
        async def start(self):
            raise RuntimeError("启动失败")

        async def stop(self):
            return None

    lifecycle = compile_proactive_lifecycle(
        [BrokenStopModule("first"), BrokenStartModule("second")]
    )

    with pytest.raises(RuntimeError, match="启动失败") as captured:
        asyncio.run(lifecycle.start())

    assert captured.value.__cause__ is not None
    assert "停止失败" in str(captured.value.__cause__)


def test_compiler_rejects_synchronous_module_hook():
    """同步回调必须在编译期拒绝，不能留到后台 tick 才失败。"""

    class SynchronousModule:
        slot = "sync"
        requires = ()
        produces = ()

        def run(self, context):
            return context

    with pytest.raises(ValueError, match="异步"):
        compile_proactive_lifecycle([SynchronousModule()])


def test_pipeline_runs_compiled_extensions_after_default_tick():
    """扩展模块只能在默认 tick 完成后读取其结果。"""

    from application.proactive.infra.data_gateway import DataGateway
    from application.proactive.infra.gate import AnyActionGate, ProactiveStateStore
    from application.proactive.app.judge_loop import JudgeLoop
    from application.proactive.infra.mcp_pool import McpClientPool
    from application.proactive.app.pipeline import ProactiveTurnPipeline

    seen = []

    class Extension(_Module):
        async def run(self, tick):
            seen.append(tick.gate_result.passed)
            return tick

    pipeline = ProactiveTurnPipeline(
        state_store=ProactiveStateStore(),
        gateway=DataGateway(McpClientPool()),
        judge=JudgeLoop(llm_client=_SkipLLM()),
        any_action=AnyActionGate(max_per_day=100),
        lifecycle=compile_proactive_lifecycle([Extension("extension")]),
    )

    asyncio.run(pipeline.run(chat_id="chat", base_score=1.0))

    assert seen == [True]


def test_pipeline_extensions_share_declared_data_slots():
    """后续模块必须能读取前一模块生产的数据槽。"""

    from application.proactive.infra.data_gateway import DataGateway
    from application.proactive.infra.gate import AnyActionGate, ProactiveStateStore
    from application.proactive.app.judge_loop import JudgeLoop
    from application.proactive.infra.mcp_pool import McpClientPool
    from application.proactive.app.pipeline import ProactiveTurnPipeline

    seen = []

    class Producer(_Module):
        async def run(self, context):
            context.slots["proactive:annotation"] = "ready"
            return context

    class Consumer(_Module):
        async def run(self, context):
            seen.append(context.slots["proactive:annotation"])
            return context

    lifecycle = compile_proactive_lifecycle(
        [
            Consumer("consumer", requires=("proactive:annotation",)),
            Producer("producer", produces=("proactive:annotation",)),
        ]
    )
    pipeline = ProactiveTurnPipeline(
        state_store=ProactiveStateStore(),
        gateway=DataGateway(McpClientPool()),
        judge=JudgeLoop(llm_client=_SkipLLM()),
        any_action=AnyActionGate(max_per_day=100),
        lifecycle=lifecycle,
    )

    asyncio.run(pipeline.run(chat_id="chat", base_score=1.0))

    assert seen == ["ready"]


def test_loop_starts_and_stops_pipeline_extensions_with_resources():
    """主动循环必须在资源可用后启动扩展，并在关闭资源前停止它们。"""

    from application.proactive.app.loop import ProactiveLoop

    events: list[str] = []

    class Pool:
        async def connect_all(self):
            events.append("connect")

        async def close_all(self):
            events.append("close")

    class Pipeline:
        async def start_extensions(self):
            events.append("start_extensions")

        async def stop_extensions(self):
            events.append("stop_extensions")

        def close(self):
            events.append("pipeline_close")

    loop = ProactiveLoop(pipeline=Pipeline(), mcp_pool=Pool())

    async def scenario():
        await loop._connect_resources()
        await loop._close_resources()

    asyncio.run(scenario())

    assert events == [
        "connect",
        "start_extensions",
        "stop_extensions",
        "close",
        "pipeline_close",
    ]


def test_runtime_compiles_registered_proactive_modules():
    """运行时工厂必须在启动前编译插件声明的主动模块。"""

    from application.proactive.app.runtime import build_proactive_runtime

    class Pool:
        async def connect_all(self):
            return None

        async def close_all(self):
            return None

    runtime = build_proactive_runtime(
        chat_id="chat",
        llm_client=_SkipLLM(),
        mcp_pool=Pool(),
        proactive_modules=[_Module("extension")],
    )

    assert runtime._pipeline._lifecycle.slots == ("extension",)


class _SkipLLM:
    """返回跳过结果的最小模型替身。"""

    def generate(self, messages, tools=None):
        del messages, tools
        return type("Response", (), {"content": "", "tool_calls": []})()
