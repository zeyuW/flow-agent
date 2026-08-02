"""把用户回合事件接入主动链路的霍克斯调度器。"""

from __future__ import annotations

from dataclasses import dataclass

from infra.messaging.event_bus import Event
from flow_agent.proactive.proactive_loop import ProactiveLoop


@dataclass(slots=True)
class ProactiveEventBridge:
    """仅把目标会话的已提交用户回合转换为互动事件。"""

    loop: ProactiveLoop
    target_session_id: str
    target_channel: str = ""

    def on_event(self, event: Event) -> None:
        """过滤无关事件并记录真实用户互动。"""

        if event.event_type != "turn_committed":
            return
        if self.target_session_id and event.session_id != self.target_session_id:
            return
        channel = str(event.payload.get("channel") or "")
        if self.target_channel and channel != self.target_channel:
            return
        timestamp = event.timestamp.timestamp()
        self.loop.record_user_interaction(
            "user_message",
            timestamp=timestamp,
        )
