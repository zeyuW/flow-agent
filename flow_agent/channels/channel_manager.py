from __future__ import annotations

from dataclasses import dataclass, field

from flow_agent.channels.base import Channel
from flow_agent.ops.audit import AuditLogger
from flow_agent.ops.incidents import IncidentStore
from flow_agent.ops.metrics import MetricsStore


@dataclass(slots=True)
class ChannelManager:
    channels: dict[str, Channel] = field(default_factory=dict)
    metrics: MetricsStore = field(default_factory=MetricsStore)
    incidents: IncidentStore = field(default_factory=IncidentStore)
    audit: AuditLogger | None = None

    def register(self, channel: Channel) -> None:
        self.channels[channel.name] = channel

    def start(self, name: str) -> None:
        channel = self._get(name)
        try:
            channel.start()
            self.metrics.inc(f"channel.{name}.start_ok")
            self._audit("channel_start", {"channel": name})
        except Exception as exc:
            self.metrics.inc(f"channel.{name}.start_failed")
            self.incidents.report("channel_start_failed", str(exc), {"channel": name})
            raise

    def stop(self, name: str) -> None:
        channel = self._get(name)
        try:
            channel.stop()
            self.metrics.inc(f"channel.{name}.stop_ok")
            self._audit("channel_stop", {"channel": name})
        except Exception as exc:
            self.metrics.inc(f"channel.{name}.stop_failed")
            self.incidents.report("channel_stop_failed", str(exc), {"channel": name})
            raise

    def status(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for name, channel in self.channels.items():
            s = channel.status()
            result[name] = {"running": s.running, "last_error": s.last_error}
        return result

    def _get(self, name: str) -> Channel:
        channel = self.channels.get(name)
        if channel is None:
            raise ValueError(f"unknown channel: {name}")
        return channel

    def _audit(self, action: str, payload: dict[str, object]) -> None:
        if self.audit is not None:
            self.audit.record(action=action, actor="system", payload=payload)
