"""事件总线：实现 fanout 扇出广播，用于生命周期事件通知。

EventBus 与 MessageBus 完全独立：
- EventBus: 事件广播（TurnCommitted 等生命周期事件），扇出给所有订阅者
- MessageBus: 消息传输（入站/出站消息），点对点队列
"""

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol, TypeVar

logger = logging.getLogger(__name__)

EventHandler = TypeVar("EventHandler")


class EventSubscription:
    """有序生命周期处理器的可撤销订阅。"""

    def __init__(
        self,
        bus: "EventBus",
        event_type: type[object],
        handler: Callable[..., object],
    ) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._closed = False

    def close(self) -> None:
        """撤销订阅；重复关闭不会产生副作用。"""

        if self._closed:
            return
        self._closed = True
        self._bus.off(self._event_type, self._handler)


def _invoke_result(result: object) -> Awaitable[object] | None:
    if inspect.isawaitable(result):
        return result




def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Event:
    """事件基类。"""

    __slots__ = ("event_type", "trace_id", "session_id", "timestamp", "payload")

    def __init__(
        self,
        event_type: str,
        trace_id: str = "",
        session_id: str = "",
        timestamp: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.event_type = event_type
        self.trace_id = trace_id
        self.session_id = session_id
        self.timestamp = timestamp or _utc_now()
        self.payload = payload or {}


class TurnCommitted(Event):
    """回合提交事件：在 AfterTurn 阶段通过 EventBus 广播。

    表示一个完整对话回合已经提交结束，
    记忆系统、监控、仪表盘等订阅者通过此事件获知更新。
    """

    __slots__ = ("user_input", "assistant_output", "tool_trace")

    def __init__(
        self,
        trace_id: str = "",
        session_id: str = "",
        user_input: str = "",
        assistant_output: str = "",
        tool_trace: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(
            event_type="turn_committed",
            trace_id=trace_id,
            session_id=session_id,
            payload={
                "user_input": user_input,
                "assistant_output": assistant_output,
                "tool_trace": tool_trace or [],
            },
        )
        self.user_input = user_input
        self.assistant_output = assistant_output
        self.tool_trace = tool_trace or []


class StreamDeltaReady(Event):
    """流式输出增量事件：在生成过程中实时广播。

    用于渠道实时显示模型思考过程或生成内容。
    """

    __slots__ = ("delta", "channel", "chat_id")

    def __init__(
        self,
        trace_id: str = "",
        session_id: str = "",
        delta: str = "",
        channel: str = "",
        chat_id: str = "",
    ) -> None:
        super().__init__(
            event_type="stream_delta_ready",
            trace_id=trace_id,
            session_id=session_id,
            payload={
                "delta": delta,
                "channel": channel,
                "chat_id": chat_id,
            },
        )
        self.delta = delta
        self.channel = channel
        self.chat_id = chat_id


class ToolCallStarted(Event):
    """工具调用开始事件：在工具调用开始时广播。

    用于渠道实时显示工具调用状态。
    """

    __slots__ = ("tool_name", "tool_args", "channel", "chat_id")

    def __init__(
        self,
        trace_id: str = "",
        session_id: str = "",
        tool_name: str = "",
        tool_args: dict[str, str] | None = None,
        channel: str = "",
        chat_id: str = "",
    ) -> None:
        super().__init__(
            event_type="tool_call_started",
            trace_id=trace_id,
            session_id=session_id,
            payload={
                "tool_name": tool_name,
                "tool_args": tool_args or {},
                "channel": channel,
                "chat_id": chat_id,
            },
        )
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.channel = channel
        self.chat_id = chat_id


class ToolCallCompleted(Event):
    """工具调用完成事件：在工具调用完成时广播。

    用于渠道实时显示工具调用结果。
    """

    __slots__ = ("tool_name", "result", "channel", "chat_id")

    def __init__(
        self,
        trace_id: str = "",
        session_id: str = "",
        tool_name: str = "",
        result: str = "",
        channel: str = "",
        chat_id: str = "",
    ) -> None:
        super().__init__(
            event_type="tool_call_completed",
            trace_id=trace_id,
            session_id=session_id,
            payload={
                "tool_name": tool_name,
                "result": result,
                "channel": channel,
                "chat_id": chat_id,
            },
        )
        self.tool_name = tool_name
        self.result = result
        self.channel = channel
        self.chat_id = chat_id


class EventSubscriber(Protocol):
    """事件订阅者协议。"""

    def on_event(self, event: Event) -> None:
        ...


@dataclass
class EventBus:
    """事件总线：fanout 扇出广播。

    支持多个订阅者，当 publish 被调用时，所有订阅者都会收到事件。
    与 MessageBus 完全独立，不涉及消息传输。
    """

    _subscribers: list[EventSubscriber] = field(default_factory=list)

    _handlers: dict[type[object], list[Callable[..., object]]] = field(
        default_factory=dict
    )

    def on(
        self,
        event_type: type[EventHandler],
        handler: Callable[[EventHandler], object],
    ) -> EventSubscription:
        """注册按类型执行的生命周期处理器，并保留注册顺序。"""

        handlers = self._handlers.setdefault(event_type, [])
        handlers.append(handler)
        return EventSubscription(self, event_type, handler)

    def on_any(self, handler: Callable[[object], object]) -> EventSubscription:
        """注册接收所有事件的处理器。"""

        return self.on(object, handler)

    def off(self, event_type: type[object], handler: Callable[..., object]) -> None:
        """移除一个生命周期处理器。"""

        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return
        if not handlers:
            del self._handlers[event_type]

    @property
    def handler_count(self) -> int:
        """返回当前生命周期处理器总数。"""

        return sum(len(handlers) for handlers in self._handlers.values())

    def _handlers_for(self, event: object) -> list[Callable[..., object]]:
        return [
            *self._handlers.get(type(event), []),
            *self._handlers.get(object, []),
        ]

    async def emit(self, event: Event) -> Event:
        """按注册顺序执行拦截链，非空返回值替换当前事件。"""

        current = event
        for handler in self._handlers_for(current):
            result = handler(current)
            awaitable = _invoke_result(result)
            if awaitable is not None:
                result = await awaitable
            if result is not None:
                current = result
        return current

    async def observe(self, event: Event) -> None:
        """顺序执行观察处理器，单个处理器失败不影响其他处理器。"""

        for handler in self._handlers_for(event):
            try:
                result = handler(event)
                awaitable = _invoke_result(result)
                if awaitable is not None:
                    await awaitable
            except Exception:
                logger.exception("event observer failed: %s", type(event).__name__)

    async def fanout(self, event: Event) -> None:
        """并行执行观察处理器，并隔离单个处理器异常。"""

        handlers = self._handlers_for(event)
        if not handlers:
            return

        async def run(handler: Callable[..., object]) -> None:
            try:
                result = handler(event)
                awaitable = _invoke_result(result)
                if awaitable is not None:
                    await awaitable
            except Exception:
                logger.exception(
                    "event fanout observer failed: %s", type(event).__name__
                )

        await asyncio.gather(*(run(handler) for handler in handlers))


    def subscribe(self, subscriber: EventSubscriber) -> None:
        """订阅事件总线。"""
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)
            logger.debug("event subscriber registered: %s", type(subscriber).__name__)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        """取消订阅。"""
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def publish(self, event: Event) -> None:
        """发布事件，扇出给所有订阅者。"""
        logger.debug("event published: type=%s trace=%s", event.event_type, event.trace_id)
        for sub in self._subscribers:
            try:
                sub.on_event(event)
            except Exception:
                logger.exception("event subscriber %s failed", type(sub).__name__)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
