"""模块上下文，在模块之间传递数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from flow_agent.proactive.models import JudgeResult, ResolveResult


@dataclass
class ModuleContext:
    """模块上下文。

    在各个模块之间传递数据和状态。
    """
    chat_id: str
    is_busy: bool
    base_score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # 数据相关
    raw_data: list[dict] | None = None
    judge_result: JudgeResult | None = None
    resolve_result: ResolveResult | None = None
    
    # 状态相关
    gate_passed: bool = False
    gate_reason: str = ""
    
    # 模块间通信
    shared_data: dict[str, Any] = field(default_factory=dict)

    def with_metadata(self, **kwargs) -> ModuleContext:
        """更新元数据。"""
        # 处理特殊字段
        gate_passed = kwargs.pop('gate_passed', self.gate_passed)
        gate_reason = kwargs.pop('gate_reason', self.gate_reason)
        
        return ModuleContext(
            chat_id=self.chat_id,
            is_busy=self.is_busy,
            base_score=self.base_score,
            metadata={**(self.metadata or {}), **kwargs},
            raw_data=self.raw_data,
            judge_result=self.judge_result,
            resolve_result=self.resolve_result,
            gate_passed=gate_passed,
            gate_reason=gate_reason,
            shared_data=self.shared_data.copy(),
        )

    def with_shared_data(self, **kwargs) -> ModuleContext:
        """更新共享数据。"""
        # 处理特殊字段
        gate_passed = kwargs.pop('gate_passed', self.gate_passed) if 'gate_passed' in kwargs else self.gate_passed
        gate_reason = kwargs.pop('gate_reason', self.gate_reason) if 'gate_reason' in kwargs else self.gate_reason
        
        return ModuleContext(
            chat_id=self.chat_id,
            is_busy=self.is_busy,
            base_score=self.base_score,
            metadata=self.metadata.copy(),
            raw_data=self.raw_data,
            judge_result=self.judge_result,
            resolve_result=self.resolve_result,
            gate_passed=gate_passed,
            gate_reason=gate_reason,
            shared_data={**(self.shared_data or {}), **kwargs},
        )

    def get_slot(self, slot_name: str, default: Any = None) -> Any:
        """获取槽位数据。"""
        return self.shared_data.get(slot_name, default)

    def set_slot(self, slot_name: str, value: Any) -> ModuleContext:
        """设置槽位数据，返回 self 以支持链式调用。"""
        self.shared_data[slot_name] = value
        return self
