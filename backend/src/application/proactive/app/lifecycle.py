"""主动扩展模块的声明校验、依赖编译与生命周期管理。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any


_RunHook = Callable[[Any], Awaitable[Any]]
_LifecycleHook = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class _CompiledModule:
    """固定模块声明，避免运行期反复读取可变插件属性。"""

    slot: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    run: _RunHook
    start: _LifecycleHook | None
    stop: _LifecycleHook | None


@dataclass(slots=True)
class ProactiveModuleContext:
    """为单次主动 tick 提供默认结果和扩展数据槽。"""

    tick: Any
    slots: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        """兼容模块直接读取 AgentTick 已有字段的简单写法。"""

        return getattr(self.tick, name)


class ProactiveLifecycle:
    """已编译的主动模块执行计划。"""

    def __init__(self, modules: tuple[_CompiledModule, ...]) -> None:
        self._modules = modules
        self._started: list[_CompiledModule] = []

    @property
    def slots(self) -> tuple[str, ...]:
        """返回拓扑排序后的模块标识，供诊断和测试使用。"""

        return tuple(module.slot for module in self._modules)

    async def start(self) -> None:
        """按编译顺序启动模块；失败时逆序回滚已启动资源。"""

        if self._started:
            return
        started: list[_CompiledModule] = []
        try:
            for module in self._modules:
                # 启动过程本身也可能取得部分资源，必须纳入失败回滚范围。
                started.append(module)
                if module.start is not None:
                    await module.start()
        except BaseException as start_error:
            try:
                await self._stop_modules(reversed(started))
            except BaseException as stop_error:
                raise start_error from stop_error
            raise
        self._started = started

    async def run(self, context: Any) -> Any:
        """按已验证的顺序执行当前 tick 的全部扩展模块。"""

        for module in self._modules:
            context = await module.run(context)
        return context

    async def stop(self) -> None:
        """逆序释放已启动模块，确保依赖方先于依赖资源结束。"""

        started, self._started = self._started, []
        await self._stop_modules(reversed(started))

    async def _stop_modules(self, modules: Iterable[_CompiledModule]) -> None:
        """尽力停止模块，并在全部清理后报告第一个停止错误。"""

        first_error: BaseException | None = None
        for module in modules:
            if module.stop is None:
                continue
            try:
                await asyncio.shield(module.stop())
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


def compile_proactive_lifecycle(
    modules: Iterable[object],
    *,
    initial_slots: Iterable[str] = (),
) -> ProactiveLifecycle:
    """校验声明式模块并生成稳定的拓扑执行计划。"""

    compiled = tuple(_compile_module(module) for module in modules)
    _validate_unique_slots(compiled)
    producers = _build_producers(compiled)
    dependencies = _expand_dependencies(compiled, producers, set(initial_slots))
    ordered_slots = _stable_topological_sort(compiled, dependencies)
    by_slot = {module.slot: module for module in compiled}
    return ProactiveLifecycle(tuple(by_slot[slot] for slot in ordered_slots))


def _compile_module(module: object) -> _CompiledModule:
    """读取并冻结模块契约，尽早拒绝动态或不完整声明。"""

    name = type(module).__name__
    slot = getattr(module, "slot", None)
    if not isinstance(slot, str) or not slot:
        raise ValueError(f"主动模块缺少有效 slot: {name}")
    requires = _read_slot_names(module, "requires")
    produces = _read_slot_names(module, "produces")
    run = _read_hook(module, "run", required=True)
    start = _read_hook(module, "start", required=False)
    stop = _read_hook(module, "stop", required=False)
    return _CompiledModule(
        slot=slot,
        requires=requires,
        produces=produces,
        run=run,
        start=start,
        stop=stop,
    )


def _read_slot_names(module: object, field: str) -> tuple[str, ...]:
    """读取槽名称列表，禁止字符串被误当成可迭代声明。"""

    value = getattr(module, field, ())
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ValueError(f"主动模块字段必须是槽名称列表: {field}")
    values = tuple(value)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"主动模块字段包含无效槽名称: {field}")
    return values


def _read_hook(module: object, field: str, *, required: bool):
    """读取异步回调；运行入口不可缺失，生命周期钩子可省略。"""

    hook = getattr(module, field, None)
    if hook is None and not required:
        return None
    if not callable(hook):
        raise ValueError(f"主动模块回调不可调用: {field}")
    if not inspect.iscoroutinefunction(hook):
        raise ValueError(f"主动模块回调必须是异步函数: {field}")
    return hook


def _validate_unique_slots(modules: tuple[_CompiledModule, ...]) -> None:
    """模块标识是图节点身份，重复时无法确定依赖边。"""

    slots = [module.slot for module in modules]
    if len(slots) != len(set(slots)):
        raise ValueError("主动模块 slot 重复")


def _build_producers(
    modules: tuple[_CompiledModule, ...],
) -> dict[str, str]:
    """建立数据槽到唯一生产模块的映射。"""

    producers: dict[str, str] = {}
    for module in modules:
        for data_slot in module.produces:
            previous = producers.setdefault(data_slot, module.slot)
            if previous != module.slot:
                raise ValueError(f"主动数据槽存在重复生产者: {data_slot}")
    return producers


def _expand_dependencies(
    modules: tuple[_CompiledModule, ...],
    producers: dict[str, str],
    initial_slots: set[str],
) -> dict[str, set[str]]:
    """把数据依赖转换为模块依赖，并拒绝没有来源的输入。"""

    module_slots = {module.slot for module in modules}
    dependencies: dict[str, set[str]] = {}
    for module in modules:
        required_modules: set[str] = set()
        for required in module.requires:
            if required in module_slots:
                required_modules.add(required)
                continue
            producer = producers.get(required)
            if producer is not None:
                required_modules.add(producer)
                continue
            if required not in initial_slots:
                raise ValueError(
                    f"主动模块数据依赖不存在: module={module.slot} slot={required}"
                )
        dependencies[module.slot] = required_modules
    return dependencies


def _stable_topological_sort(
    modules: tuple[_CompiledModule, ...],
    dependencies: dict[str, set[str]],
) -> tuple[str, ...]:
    """使用声明顺序作为并列节点次序，生成可预测的拓扑顺序。"""

    remaining = {slot: set(values) for slot, values in dependencies.items()}
    ordered: list[str] = []
    declared_order = tuple(module.slot for module in modules)
    while remaining:
        ready = [slot for slot in declared_order if slot in remaining and not remaining[slot]]
        if not ready:
            raise ValueError("主动模块依赖存在循环")
        for slot in ready:
            ordered.append(slot)
            remaining.pop(slot)
        for required in remaining.values():
            required.difference_update(ready)
    return tuple(ordered)
