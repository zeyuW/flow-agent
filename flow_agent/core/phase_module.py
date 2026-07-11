"""阶段模块接口：插件通过 PhaseModule 在管道的任意阶段介入流程。

每个阶段模块实现对应阶段的钩子方法，
管道在每个阶段执行前后调用相应的钩子，
允许插件修改 TurnFlow 数据或执行副作用操作。

TurnStarted 事件在 AgentLoop 消费消息后发布，
TurnCommitted 事件在 AfterTurn 阶段广播。
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class TurnFlow:
    """贯穿整个管道回合的数据流。

    管道的六个阶段按顺序读写此对象的字段，
    阶段模块可以在此对象上挂载自定义数据。
    """

    user_input: str
    session_id: str
    channel: str
    trace_id: str

    # 入站消息的原始 metadata（用于渠道特定信息传递）
    inbound_metadata: dict[str, Any] = field(default_factory=dict)

    # PromptRender 阶段产出
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)

    # Reasoner 阶段产出
    final_output: str = ""
    tool_trace: list[dict[str, str]] = field(default_factory=list)

    # 记忆/检索相关
    memory_block: str = ""
    retrieval_trace: list[dict[str, str]] = field(default_factory=list)

    # 中断续跑支持：上一轮的部分回复和工具调用
    previous_partial_output: str = ""
    previous_tool_trace: list[dict[str, str]] = field(default_factory=list)

    # 扩展数据：阶段模块可以在此挂载任意数据
    extensions: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PhaseModule(Protocol):
    """阶段模块协议：插件实现此接口以介入管道阶段。"""

    @property
    def name(self) -> str:
        """模块名称，用于日志和调试。"""
        ...

    def on_turn_started(self, flow: TurnFlow) -> None:
        """TurnStarted 阶段：AgentLoop 消费消息后调用。"""
        ...

    def on_before_turn(self, flow: TurnFlow) -> None:
        """BeforeTurn 阶段：回合开始前调用。"""
        ...

    def on_before_reasoning(self, flow: TurnFlow) -> None:
        """BeforeReasoning 阶段：推理开始前调用。"""
        ...

    def on_prompt_render(self, flow: TurnFlow) -> None:
        """PromptRender 阶段：提示词组装时调用。"""
        ...

    def on_after_reasoning(self, flow: TurnFlow) -> None:
        """AfterReasoning 阶段：推理结束后调用。"""
        ...

    def on_after_turn(self, flow: TurnFlow) -> None:
        """AfterTurn 阶段：回合结束后调用（EventBus 广播和出站投递之前）。"""
        ...